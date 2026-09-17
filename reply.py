"""Ответ агента в тему группы. Текст читается со stdin: argv на Windows приходит в ANSI и портит кириллицу.

    echo текст | python reply.py --thread 42
    python reply.py --thread 42 < ответ.txt
    python reply.py --thread 42 --voice ответ.ogg < подпись.txt
    python reply.py --thread 42 --video прогон.mp4 < подпись.txt
    python reply.py --thread 42 --file отчёт.zip < подпись.txt
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import Bot, ReplyParameters
from telegram.constants import FileSizeLimit

import state

PROJECT_DIR = Path(__file__).resolve().parent
TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
GENERAL_LANE = "general"
NO_QUOTE = -1
UPLOAD_SECONDS = 300
ATTACHMENT_KINDS = ("voice", "photo", "video", "file")
SHRINK_HINTS = {
    "voice": "пережми звук (ffmpeg -i вход.ogg -b:a 24k выход.ogg)",
    "photo": "уменьши картинку или отправь её же через --file",
    "video": "пережми видео (ffmpeg -i вход.mp4 -vcodec libx264 -crf 30 выход.mp4)",
    "file": "заархивируй, разрежь на части или отдай ссылкой на путь в файловой системе",
}


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if len(value) == 0:
        raise SystemExit(f"reply: переменная {name} не задана — отправлять некуда")
    return value


def read_stdin_text() -> str:
    text = sys.stdin.buffer.read().decode("utf-8", "replace").strip()
    if len(text) == 0:
        raise SystemExit("reply: пустой stdin — нечего отправлять")
    return text


def chunks(text: str) -> list[str]:
    return [text[start:start + TELEGRAM_TEXT_LIMIT] for start in range(0, len(text), TELEGRAM_TEXT_LIMIT)]


def split_caption(text: str) -> tuple[str, str]:
    """Подпись к медиа Telegram обрезает по 1024 символа, поэтому хвост уходит отдельными сообщениями."""
    if len(text) <= TELEGRAM_CAPTION_LIMIT:
        return text, ""
    edge = text.rfind("\n\n", 0, TELEGRAM_CAPTION_LIMIT)
    if edge < TELEGRAM_CAPTION_LIMIT // 3:
        edge = text.rfind(" ", 0, TELEGRAM_CAPTION_LIMIT)
    return text[:edge].strip(), text[edge:].strip()


def lane_key(thread: int) -> str:
    """Ключ ленты: у темы это её id, у General — общее имя, как его пишет router."""
    if thread > 0:
        return str(thread)
    return GENERAL_LANE


def upload_limit(kind: str) -> int:
    """Bot API принимает multipart-загрузку до 10 МБ для фото и до 50 МБ для всего остального."""
    if kind == "photo":
        return int(FileSizeLimit.PHOTOSIZE_UPLOAD)
    return int(FileSizeLimit.FILESIZE_UPLOAD)


def checked_path(kind: str, name: str) -> Path:
    """Размер сверяется до загрузки: иначе отказ прилетает от Telegram через минуты заливки."""
    path = Path(name)
    if path.is_file() is False:
        raise SystemExit(f"reply: файл {path} не найден")
    limit = upload_limit(kind)
    size = path.stat().st_size
    if size > limit:
        raise SystemExit(
            f"reply: {path} весит {size / 1_000_000:.1f} МБ, Bot API принимает до {limit // 1_000_000} МБ — {SHRINK_HINTS[kind]}"
        )
    return path


def chosen_attachment(args: argparse.Namespace) -> tuple[str, str]:
    """Взаимоисключающая группа argparse не даст указать два вида вложения разом."""
    for kind in ATTACHMENT_KINDS:
        name = getattr(args, kind)
        if len(name) > 0:
            return kind, name
    return "", ""


def quoting(message_id: int) -> dict:
    """Цитата на конкретное сообщение. Bot API 7.0 заменил reply_to_message_id на reply_parameters,
    а allow_sending_without_reply внутри них оставляет ответ доставленным, если исходное удалили."""
    if message_id < 1:
        return {}

    return {"reply_parameters": ReplyParameters(message_id=message_id, allow_sending_without_reply=True)}


def last_unanswered(lane: str) -> int:
    """Кому отвечаем, когда цитату не назвали руками: самое свежее сообщение без ответа,
    а если отвечено уже на всё — последнее пришедшее, чтобы ответ всё равно был адресным."""
    waiting = [message_id for message_id in state.read_pending(lane) if isinstance(message_id, int)]

    if len(waiting) > 0:
        return max(waiting)

    return last_incoming(lane)


def last_incoming(lane: str) -> int:
    """Последнее сообщение ленты: лента пишется router и хранит всё, что человек прислал."""
    path = state.state_dir() / "inbox" / f"{lane}.jsonl"

    if path.is_file() is False:
        return 0

    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        if len(line.strip()) == 0:
            continue

        return int(json.loads(line)["message_id"])

    return 0


async def send_attachment(bot: Bot, chat_id: int, kind: str, path: Path, caption: str, topic: int | None, quoted: int) -> int:
    senders = {
        "voice": bot.send_voice,
        "photo": bot.send_photo,
        "video": bot.send_video,
        "file": bot.send_document,
    }
    streaming = {"supports_streaming": True} if kind == "video" else {}
    with path.open("rb") as handle:
        delivered = await senders[kind](
            chat_id,
            handle,
            caption=caption,
            message_thread_id=topic,
            write_timeout=UPLOAD_SECONDS,
            read_timeout=UPLOAD_SECONDS,
            **quoting(quoted),
            **streaming,
        )
    return delivered.message_id


async def send(thread: int, text: str, kind: str, path: Path | None, reply_to: int = 0) -> list[int]:
    """Возвращает id отправленных сообщений: молчаливый успех неотличим от отказа и провоцирует повторную отправку."""
    bot = Bot(require_env("AI_PAIR_BOT_TOKEN"))
    chat_id = int(require_env("AI_PAIR_CHAT_ID"))
    topic = thread if thread > 0 else None
    lane = lane_key(thread)
    quoted = reply_to if reply_to != 0 else last_unanswered(lane)
    sent = []
    async with bot:
        if path is not None:
            caption, rest = split_caption(text)
            sent.append(await send_attachment(bot, chat_id, kind, path, caption, topic, quoted))
            for part in chunks(rest):
                delivered = await bot.send_message(chat_id, part, message_thread_id=topic)
                sent.append(delivered.message_id)
            await clear_seen(bot, chat_id, lane)
            return sent
        for part in chunks(text):
            delivered = await bot.send_message(chat_id, part, message_thread_id=topic, **quoting(quoted))
            sent.append(delivered.message_id)
            quoted = 0
        await clear_seen(bot, chat_id, lane)
    return sent


async def clear_seen(bot: Bot, chat_id: int, lane: str) -> None:
    """Реакции снимаются только с сообщений чата: вводные из кода приходят меткой «файл:строка»."""
    state.mark("reported", lane)
    for waiting in state.take_pending(lane):
        if isinstance(waiting, int):
            await bot.set_message_reaction(chat_id, waiting, reaction=[])


def receipt(thread: int, sent: list[int]) -> str:
    """Расписка о доставке: без неё повторный запуск выглядит как единственный способ убедиться, что сообщение ушло."""
    where = f"тему {thread}" if thread > 0 else "General"
    ids = ", ".join(str(message_id) for message_id in sent)
    return f"reply: отправлено в {where}, сообщений {len(sent)} (id {ids})"


def main() -> None:
    parser = argparse.ArgumentParser(description="отправить ответ агента в тему группы")
    parser.add_argument("--thread", type=int, default=0, help="message_thread_id темы проекта; без него сообщение уйдёт в General")
    attachment = parser.add_mutually_exclusive_group()
    attachment.add_argument("--voice", default="", help="путь к .ogg, чтобы отправить голосовым, а не документом")
    attachment.add_argument("--photo", default="", help="путь к картинке: уйдёт фото, текст станет подписью")
    attachment.add_argument("--video", default="", help="путь к .mp4: уйдёт видео с плеером, текст станет подписью")
    attachment.add_argument("--file", default="", help="путь к любому файлу: уйдёт документом, текст станет подписью")
    parser.add_argument("--reply-to", type=int, default=0, dest="reply_to", help="message_id входящего сообщения: ответ уйдёт цитатой")
    parser.add_argument("--no-quote", action="store_const", const=NO_QUOTE, default=0, dest="quote_off", help="сообщение от себя: без цитаты, ничего не отвечаем")
    args = parser.parse_args()
    load_dotenv(PROJECT_DIR / ".env")
    kind, name = chosen_attachment(args)
    path = checked_path(kind, name) if len(kind) > 0 else None
    sent = asyncio.run(send(args.thread, read_stdin_text(), kind, path, args.reply_to or args.quote_off))
    print(receipt(args.thread, sent))


if __name__ == "__main__":
    main()
