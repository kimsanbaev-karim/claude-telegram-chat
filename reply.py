"""Ответ агента в тему группы. Текст читается со stdin: argv на Windows приходит в ANSI и портит кириллицу.

    echo текст | python reply.py --thread 42
    python reply.py --thread 42 < ответ.txt
    python reply.py --thread 42 --voice ответ.ogg < подпись.txt
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import Bot

import state

PROJECT_DIR = Path(__file__).resolve().parent
TELEGRAM_TEXT_LIMIT = 4096


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


async def send(thread: int, text: str, voice: str, reply_to: int = 0, photo: str = "") -> None:
    bot = Bot(require_env("AI_PAIR_BOT_TOKEN"))
    chat_id = int(require_env("AI_PAIR_CHAT_ID"))
    quoted = reply_to if reply_to > 0 else None
    async with bot:
        if len(voice) > 0:
            audio = Path(voice)
            if audio.is_file() is False:
                raise SystemExit(f"reply: файл {audio} не найден")
            with audio.open("rb") as handle:
                await bot.send_voice(chat_id, handle, caption=text[:1024], message_thread_id=thread, reply_to_message_id=quoted)
            await clear_seen(bot, chat_id, thread)
            return
        if len(photo) > 0:
            image = Path(photo)
            if image.is_file() is False:
                raise SystemExit(f"reply: файл {image} не найден")
            with image.open("rb") as handle:
                await bot.send_photo(chat_id, handle, caption=text[:1024], message_thread_id=thread, reply_to_message_id=quoted)
            await clear_seen(bot, chat_id, thread)
            return
        for part in chunks(text):
            await bot.send_message(chat_id, part, message_thread_id=thread, reply_to_message_id=quoted)
        await clear_seen(bot, chat_id, thread)


async def clear_seen(bot: Bot, chat_id: int, thread: int) -> None:
    for message_id in state.take_pending(str(thread)):
        await bot.set_message_reaction(chat_id, message_id, reaction=[])


def main() -> None:
    parser = argparse.ArgumentParser(description="отправить ответ агента в тему группы")
    parser.add_argument("--thread", type=int, required=True, help="message_thread_id темы проекта")
    parser.add_argument("--voice", default="", help="путь к .ogg, чтобы отправить голосовым, а не документом")
    parser.add_argument("--photo", default="", help="путь к картинке: уйдёт фото, текст станет подписью")
    parser.add_argument("--reply-to", type=int, default=0, dest="reply_to", help="message_id входящего сообщения: ответ уйдёт цитатой")
    args = parser.parse_args()
    load_dotenv(PROJECT_DIR / ".env")
    asyncio.run(send(args.thread, read_stdin_text(), args.voice, args.reply_to, args.photo))


if __name__ == "__main__":
    main()
