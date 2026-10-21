"""Единственный на машину поллер Telegram: раскладывает сообщения по лентам тем.

Запускать ровно один экземпляр: getUpdates монопольный, второй поллер того же
токена получит Conflict: terminated by other getUpdates request.
"""

import json
import os
import platform
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from typing import cast

from dotenv import load_dotenv
from telegram import Animation, Audio, CallbackQuery, Document, Message, MessageEntity, PhotoSize, ReactionTypeEmoji
from telegram import Update, Video, VideoNote, Voice
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

import ask
import media
import state

WHISPER_DEFAULT_URL = "http://127.0.0.1:8792"
WHISPER_TIMEOUT_SECONDS = 300
GENERAL_THREAD = "general"
TAKEN_REACTION = [ReactionTypeEmoji("👀")]
CONNECT_TIMEOUT = 20.0
READ_TIMEOUT = 30.0
POLL_READ_TIMEOUT = 60.0
POOL_TIMEOUT = 20.0

MediaFile = Video | Animation | VideoNote | Voice | Audio | Document
KIND_BY_TYPE = {
    Video: ("video", ".mp4"),
    Animation: ("animation", ".mp4"),
    VideoNote: ("video_note", ".mp4"),
    Voice: ("voice", ".ogg"),
    Audio: ("audio", ".mp3"),
}
DOCUMENT_KINDS = (("video/", "video"), ("audio/", "audio"), ("image/", "photo"))
VIDEO_KINDS = frozenset({"video", "animation", "video_note"})
AUDIO_KINDS = frozenset({"voice", "audio"})
MEDIA_ERRORS = (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired)


class Settings:
    def __init__(self) -> None:
        self.token = require_env("AI_PAIR_BOT_TOKEN")
        self.chat_id = int(require_env("AI_PAIR_CHAT_ID"))
        self.allowed_users = parse_user_ids(require_env("AI_PAIR_ALLOWED_USERS"))
        # чат команды: бот откликается только на свой тег или ответ на своё сообщение
        self.bot_username = os.environ.get("AI_PAIR_MENTION_ONLY", "").strip().lstrip("@")
        self.state_dir = Path(os.environ.get("AI_PAIR_STATE_DIR", Path.home() / ".claude-telegram-chat"))
        # две машины: сообщение адресует платформа, глаза ставит follow.py той, кому оно доставлено
        self.intake_reaction = os.environ.get("AI_PAIR_INTAKE_REACTION", "1") == "1"
        self.inbox_dir = self.state_dir / "inbox"
        self.media_dir = self.state_dir / "media"
        self.frames_dir = self.state_dir / "frames"


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if len(value) == 0:
        raise SystemExit(f"router: переменная {name} не задана — запуск невозможен")
    return value


def parse_user_ids(raw: str) -> frozenset[int]:
    """«*» — писать может любой участник чата: пустое множество значит «без белого списка»."""
    if raw.strip() == "*":
        return frozenset()
    ids = {int(part.strip()) for part in raw.split(",") if len(part.strip()) > 0}
    if len(ids) == 0:
        raise SystemExit("router: AI_PAIR_ALLOWED_USERS пуст — некому писать в канал; «*» — любой участник")
    return frozenset(ids)


class AddressedToBot(filters.MessageFilter):
    """Тег бота в тексте или подписи, либо ответ на его сообщение."""

    def __init__(self, username: str) -> None:
        super().__init__()
        self.username = username.lower()
        self.mention = filters.Mention(username)

    def filter(self, message: Message) -> bool:
        replied = message.reply_to_message
        author = replied.from_user if replied is not None else None
        if author is not None and f"{author.username}".lower() == self.username:
            return True
        return bool(self.mention.filter(message))


def addressed_here(message: Message, me: str) -> bool:
    """Кому сообщение (решение Карима 21.10, #9667, Unit-AI-System):
    есть тег или reply — тому, чей тег или чьё сообщение; нет ни того ни другого — сессии темы,
    если задача темы не отдана юниту (поле units в task.md), иначе юниту.
    """
    # parse_entities режет текст по UTF-16, как считает Telegram; у подписи вложения свои сущности
    entities = message.parse_caption_entities if message.caption else message.parse_entities
    tagged = {mention.lstrip("@").lower() for mention in entities([MessageEntity.MENTION]).values()}
    tagged |= {f"{e.user.username}".lower() for e in entities([MessageEntity.TEXT_MENTION]) if e.user}
    replied = message.reply_to_message
    replied_author = ""
    if replied is not None and replied.message_id != message.message_thread_id and replied.from_user is not None:
        replied_author = f"{replied.from_user.username}".lower()
    if tagged or replied_author:
        return me.lower() in tagged or replied_author == me.lower()
    return not topic_has_units(message.message_thread_id if message.is_topic_message else None)


def topic_has_units(thread: int | None) -> bool:
    """Задача темы отдана юниту: в реестре тем ищем «проект#задача», в её task.md — непустое поле units."""
    if thread is None:
        return False
    registry = state.registry_path()
    try:
        topics = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    key = next((name for name, number in topics.items() if number == thread and "#" in name), None)
    if key is None:
        return False
    project, task = key.split("#", 1)
    task_md = registry.parent.parent / "projects" / project / "tasks" / task / "task.md"
    try:
        head = task_md.read_text(encoding="utf-8").split("---", 2)
    except OSError:
        return False
    frontmatter = head[1] if len(head) > 2 else ""
    return any(line.startswith("units:") and len(line[6:].strip()) > 0 for line in frontmatter.splitlines())


def thread_key(message: Message) -> str:
    # чат команды: одна лента на весь форум, у агента один наблюдатель; тему он берёт из поля topic
    if message.is_topic_message is True and one_lane() is False:
        return str(message.message_thread_id)
    return GENERAL_THREAD


def one_lane() -> bool:
    return os.environ.get("AI_PAIR_ONE_LANE", "") == "1"


def quoted_fields(message: Message) -> dict:
    """Ответ на корень темы — не цитата: в форуме им формально отвечает каждое сообщение темы."""
    replied = message.reply_to_message
    if replied is None or replied.message_id == message.message_thread_id:
        return {}
    fields: dict = {"reply_to": replied.message_id}
    author = replied.from_user
    if author is not None and author.is_bot is True:
        fields["reply_to_bot"] = f"@{author.username}"
    return fields


def document_kind(document: Document) -> tuple[str, str]:
    """Присланный файлом ролик остаётся роликом, а песня песней: вид берём из mime."""
    suffix = Path(f"{document.file_name}").suffix
    mime = f"{document.mime_type}"
    for prefix, kind in DOCUMENT_KINDS:
        if mime.startswith(prefix) is True:
            return kind, suffix
    return "file", suffix


def attachment(message: Message) -> tuple[str, str, str]:
    """Вид вложения, его file_id и расширение, под которым оно ляжет на диск."""
    found = message.effective_attachment
    if isinstance(found, tuple):
        sizes = cast(tuple[PhotoSize, ...], found)
        return "photo", sizes[-1].file_id, ".jpg"
    if isinstance(found, Document):
        kind, suffix = document_kind(found)
        return kind, found.file_id, suffix
    single = cast(MediaFile, found)
    kind, suffix = KIND_BY_TYPE[type(single)]
    return kind, single.file_id, suffix


def transcribe(audio_path: Path) -> str:
    """Просит резидентный сервис: модель у него уже в памяти, поэтому ответ за секунды."""
    service = os.environ.get("AI_PAIR_WHISPER_URL", WHISPER_DEFAULT_URL)
    body = json.dumps({"audio": str(audio_path)}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    call = urllib.request.Request(f"{service}/transcribe", data=body, headers=headers)
    try:
        with urllib.request.urlopen(call, timeout=WHISPER_TIMEOUT_SECONDS) as answer:
            return json.loads(answer.read().decode("utf-8"))["text"].strip()
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode("utf-8", "replace").strip()[:400]) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"сервис распознавания не отвечает на {service}: {error.reason}") from error


class Router:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.inbox_dir.mkdir(parents=True, exist_ok=True)
        settings.media_dir.mkdir(parents=True, exist_ok=True)

    def append(self, message: Message, entry: dict) -> None:
        thread = thread_key(message)
        entry["thread"] = thread
        if message.is_topic_message is True and one_lane() is True:
            entry["topic"] = message.message_thread_id
        entry["message_id"] = message.message_id
        sender = message.from_user
        if sender is not None and sender.is_bot is True:
            entry["from_bot"] = f"@{sender.username}"
        elif sender is not None and len(self.settings.allowed_users) == 0:
            # без белого списка агенту надо знать, кто из участников к нему обращается
            entry["from_user"] = f"@{sender.username}" if sender.username else sender.full_name
        entry.update(quoted_fields(message))
        entry["at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        path = self.settings.inbox_dir / f"{thread}.jsonl"
        with path.open("a", encoding="utf-8", newline="\n") as lane:
            lane.write(json.dumps(entry, ensure_ascii=False) + "\n")
        sys.stderr.write(f"router: {thread} <- {entry['kind']} #{message.message_id}\n")
        sys.stderr.flush()

    async def download(self, context: ContextTypes.DEFAULT_TYPE, file_id: str, suffix: str) -> Path:
        handle = await context.bot.get_file(file_id)
        target = self.settings.media_dir / f"{handle.file_unique_id}{suffix}"
        await handle.download_to_drive(custom_path=target)
        return target

    async def mark_taken(self, context: ContextTypes.DEFAULT_TYPE, message: Message) -> None:
        """Роутер принял сообщение. Глаза ставит follow.py, когда строка уходит в сессию: иначе значок врёт при мёртвом наблюдателе."""
        state.add_pending(thread_key(message), message.message_id)
        if self.settings.intake_reaction is True:
            await context.bot.set_message_reaction(message.chat_id, message.message_id, reaction=TAKEN_REACTION)

    async def on_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = cast(CallbackQuery, update.callback_query)
        await query.answer()
        message = cast(Message, query.message)
        thread = thread_key(message)
        question_id, _, index = cast(str, query.data).partition(":")
        choice = ask.pending_question(thread)["options"][int(index)]
        ask.record_answer(question_id, choice)
        await query.edit_message_text(f"{message.text}\n\nВыбрано: {choice}")
        sys.stderr.write(f"router: {thread} <- выбор «{choice}»\n")
        sys.stderr.flush()

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = cast(Message, update.effective_message)
        if not addressed_here(message, context.bot.username):
            return
        text = cast(str, message.text)
        entry = {"kind": "text", "text": text}
        self.append(message, entry)
        await self.mark_taken(context, message)
        waiting = ask.pending_question(thread_key(message))
        if "question_id" in waiting and "from_bot" not in entry:
            ask.record_answer(waiting["question_id"], text)

    def add_frames(self, entry: dict, path: Path) -> None:
        """Ролик агент открыть не может, поэтому от него остаются равномерные кадры."""
        try:
            frames = media.extract_frames(path, self.settings.frames_dir / path.stem)
        except MEDIA_ERRORS as error:
            entry["error"] = f"кадры не извлеклись: {error}"
            return
        entry["frames"] = [str(frame) for frame in frames]

    def add_speech(self, entry: dict, path: Path) -> None:
        try:
            spoken = transcribe(path)
        except MEDIA_ERRORS as error:
            entry["error"] = f"распознавание не удалось: {error}"
            return
        entry["text"] = "\n".join(part for part in (entry["text"], spoken) if len(part) > 0)

    async def take(self, context: ContextTypes.DEFAULT_TYPE, message: Message, caption: str) -> None:
        """Отметка о приёме ставится первой: распознавание минутного голосового выглядит как мёртвый канал."""
        if not addressed_here(message, context.bot.username):
            return
        await self.mark_taken(context, message)
        kind, file_id, suffix = attachment(message)
        path = await self.download(context, file_id, suffix)
        entry: dict = {"kind": kind, "media": str(path), "text": caption}
        if kind in VIDEO_KINDS:
            self.add_frames(entry, path)
        if kind in AUDIO_KINDS:
            self.add_speech(entry, path)
        self.append(message, entry)

    async def on_attachment(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.take(context, cast(Message, update.effective_message), "")

    async def on_captioned_attachment(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = cast(Message, update.effective_message)
        await self.take(context, message, cast(str, message.caption))


def main() -> None:
    # override: трей грузит .env один раз при старте и передаёт окружение роутеру — без него правка .env
    # доходила бы до роутера только после перезапуска трея, а «перезапустить router» её не видел бы
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    # доп. бот: его .env.<имя> важнее основного .env, иначе он поллит чужой токен
    if os.environ.get("AI_PAIR_EXTRA_ENV"):
        load_dotenv(os.environ["AI_PAIR_EXTRA_ENV"], override=True)
    settings = Settings()
    router = Router(settings)
    scope = filters.Chat(chat_id=settings.chat_id)
    if len(settings.allowed_users) > 0:
        scope = scope & filters.User(user_id=settings.allowed_users)
    if len(settings.bot_username) > 0:
        scope = scope & AddressedToBot(settings.bot_username)

    api_client = HTTPXRequest(connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT, pool_timeout=POOL_TIMEOUT)
    polling_client = HTTPXRequest(connect_timeout=CONNECT_TIMEOUT, read_timeout=POLL_READ_TIMEOUT, pool_timeout=POOL_TIMEOUT)
    builder = Application.builder().token(settings.token).request(api_client).get_updates_request(polling_client)
    application = builder.build()
    attachments = filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.VIDEO_NOTE
    attachments = attachments | filters.VOICE | filters.AUDIO | filters.Document.ALL
    application.add_handler(MessageHandler(scope & filters.TEXT, router.on_text))
    application.add_handler(MessageHandler(scope & attachments & filters.CAPTION, router.on_captioned_attachment))
    application.add_handler(MessageHandler(scope & attachments & ~filters.CAPTION, router.on_attachment))
    application.add_handler(CallbackQueryHandler(router.on_choice))

    sys.stderr.write(f"router: слушаю чат {settings.chat_id}, ленты в {settings.inbox_dir}\n")
    sys.stderr.flush()
    without_wmi()
    application.run_polling(allowed_updates=["message", "callback_query"])


def without_wmi() -> None:
    """run_polling спрашивает platform.system(), а Python 3.12 узнаёт версию Windows через WMI: зависшая служба
    вешает роутер до первого getUpdates навсегда (замерено 07.10.2026, cpython gh-112278). OSError — штатный
    повод для platform взять версию из sys.getwindowsversion().
    ponytail: подмена приватного platform._wmi_query; убрать, когда CPython перестанет ходить в WMI за версией."""
    def refuse(*keys: str) -> None:
        raise OSError("WMI не используем: зависшая служба вешает platform.system()")

    platform._wmi_query = refuse  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
