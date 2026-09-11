"""Ответ агента в тему группы. Текст читается со stdin: argv на Windows приходит в ANSI и портит кириллицу.

    echo текст | python reply.py --thread 42
    python reply.py --thread 42 < ответ.txt
    python reply.py --thread 42 --voice ответ.ogg < подпись.txt
    python reply.py --thread 42 --video прогон.mp4 < подпись.txt
    python reply.py --thread 42 --file отчёт.zip < подпись.txt
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import Bot
from telegram.constants import FileSizeLimit

import state

PROJECT_DIR = Path(__file__).resolve().parent
TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
GENERAL_LANE = "general"
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


async def send_attachment(bot: Bot, chat_id: int, kind: str, path: Path, caption: str, topic: int | None, quoted: int | None) -> None:
    senders = {
        "voice": bot.send_voice,
        "photo": bot.send_photo,
        "video": bot.send_video,
        "file": bot.send_document,
    }
    streaming = {"supports_streaming": True} if kind == "video" else {}
    with path.open("rb") as handle:
        await senders[kind](
            chat_id,
            handle,
            caption=caption,
            message_thread_id=topic,
            reply_to_message_id=quoted,
            write_timeout=UPLOAD_SECONDS,
            read_timeout=UPLOAD_SECONDS,
            **streaming,
        )


async def send(thread: int, text: str, kind: str, path: Path | None, reply_to: int = 0) -> None:
    bot = Bot(require_env("AI_PAIR_BOT_TOKEN"))
    chat_id = int(require_env("AI_PAIR_CHAT_ID"))
    quoted = reply_to if reply_to > 0 else None
    topic = thread if thread > 0 else None
    lane = lane_key(thread)
    async with bot:
        if path is not None:
            caption, rest = split_caption(text)
            await send_attachment(bot, chat_id, kind, path, caption, topic, quoted)
            for part in chunks(rest):
                await bot.send_message(chat_id, part, message_thread_id=topic)
            await clear_seen(bot, chat_id, lane)
            return
        for part in chunks(text):
            await bot.send_message(chat_id, part, message_thread_id=topic, reply_to_message_id=quoted)
        await clear_seen(bot, chat_id, lane)


async def clear_seen(bot: Bot, chat_id: int, lane: str) -> None:
    state.mark("reported", lane)
    for message_id in state.take_pending(lane):
        await bot.set_message_reaction(chat_id, message_id, reaction=[])


def main() -> None:
    parser = argparse.ArgumentParser(description="отправить ответ агента в тему группы")
    parser.add_argument("--thread", type=int, default=0, help="message_thread_id темы проекта; без него сообщение уйдёт в General")
    attachment = parser.add_mutually_exclusive_group()
    attachment.add_argument("--voice", default="", help="путь к .ogg, чтобы отправить голосовым, а не документом")
    attachment.add_argument("--photo", default="", help="путь к картинке: уйдёт фото, текст станет подписью")
    attachment.add_argument("--video", default="", help="путь к .mp4: уйдёт видео с плеером, текст станет подписью")
    attachment.add_argument("--file", default="", help="путь к любому файлу: уйдёт документом, текст станет подписью")
    parser.add_argument("--reply-to", type=int, default=0, dest="reply_to", help="message_id входящего сообщения: ответ уйдёт цитатой")
    args = parser.parse_args()
    load_dotenv(PROJECT_DIR / ".env")
    kind, name = chosen_attachment(args)
    path = checked_path(kind, name) if len(kind) > 0 else None
    asyncio.run(send(args.thread, read_stdin_text(), kind, path, args.reply_to))


if __name__ == "__main__":
    main()
