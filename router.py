"""Единственный на машину поллер Telegram: раскладывает сообщения по лентам тем.

Запускать ровно один экземпляр: getUpdates монопольный, второй поллер того же
токена получит Conflict: terminated by other getUpdates request.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from typing import cast

from dotenv import load_dotenv
from telegram import Animation, Audio, CallbackQuery, Document, Message, PhotoSize, ReactionTypeEmoji
from telegram import Update, Video, VideoNote, Voice
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

import ask
import media
import state

WHISPER_TIMEOUT_SECONDS = 300
GENERAL_THREAD = "general"
SEEN_REACTION = [ReactionTypeEmoji("👀")]
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
        self.state_dir = Path(os.environ.get("AI_PAIR_STATE_DIR", Path.home() / ".claude-telegram-chat"))
        self.inbox_dir = self.state_dir / "inbox"
        self.media_dir = self.state_dir / "media"
        self.frames_dir = self.state_dir / "frames"


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if len(value) == 0:
        raise SystemExit(f"router: переменная {name} не задана — запуск невозможен")
    return value


def parse_user_ids(raw: str) -> frozenset[int]:
    ids = {int(part.strip()) for part in raw.split(",") if len(part.strip()) > 0}
    if len(ids) == 0:
        raise SystemExit("router: AI_PAIR_ALLOWED_USERS пуст — некому писать в канал")
    return frozenset(ids)


def thread_key(message: Message) -> str:
    if message.is_topic_message is True:
        return str(message.message_thread_id)
    return GENERAL_THREAD


def quoted_fields(message: Message) -> dict:
    try:
        quoted = message.reply_to_message.message_id
    except AttributeError:
        return {}
    if quoted == message.message_thread_id:
        return {}
    return {"reply_to": quoted}


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
    python = require_env("AI_PAIR_WHISPER_PYTHON")
    script = require_env("AI_PAIR_WHISPER_SCRIPT")
    command = [python, script, str(audio_path)]
    speaking = os.environ | {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run(command, capture_output=True, timeout=WHISPER_TIMEOUT_SECONDS, env=speaking)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.decode("utf-8", "replace").strip()[:400])
    return done.stdout.decode("utf-8").replace("\r\n", "\n").strip()


class Router:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.inbox_dir.mkdir(parents=True, exist_ok=True)
        settings.media_dir.mkdir(parents=True, exist_ok=True)

    def append(self, message: Message, entry: dict) -> None:
        thread = thread_key(message)
        entry["thread"] = thread
        entry["message_id"] = message.message_id
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

    async def mark_seen(self, context: ContextTypes.DEFAULT_TYPE, message: Message) -> None:
        state.add_pending(thread_key(message), message.message_id)
        await context.bot.set_message_reaction(message.chat_id, message.message_id, reaction=SEEN_REACTION)

    async def on_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = cast(CallbackQuery, update.callback_query)
        await query.answer()
        message = cast(Message, query.message)
        thread = int(cast(int, message.message_thread_id))
        question_id, _, index = cast(str, query.data).partition(":")
        choice = ask.pending_question(thread)["options"][int(index)]
        ask.record_answer(question_id, choice)
        await query.edit_message_text(f"{message.text}\n\nВыбрано: {choice}")
        sys.stderr.write(f"router: {thread} <- выбор «{choice}»\n")
        sys.stderr.flush()

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = cast(Message, update.effective_message)
        text = cast(str, message.text)
        self.append(message, {"kind": "text", "text": text})
        await self.mark_seen(context, message)
        waiting = ask.pending_question(int(thread_key(message)))
        if "question_id" in waiting:
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
        kind, file_id, suffix = attachment(message)
        path = await self.download(context, file_id, suffix)
        entry: dict = {"kind": kind, "media": str(path), "text": caption}
        if kind in VIDEO_KINDS:
            self.add_frames(entry, path)
        if kind in AUDIO_KINDS:
            self.add_speech(entry, path)
        self.append(message, entry)
        await self.mark_seen(context, message)

    async def on_attachment(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.take(context, cast(Message, update.effective_message), "")

    async def on_captioned_attachment(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = cast(Message, update.effective_message)
        await self.take(context, message, cast(str, message.caption))


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    settings = Settings()
    router = Router(settings)
    scope = filters.Chat(chat_id=settings.chat_id) & filters.User(user_id=settings.allowed_users)

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
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
