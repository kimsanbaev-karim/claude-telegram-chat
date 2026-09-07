"""Спросить человека кнопками в теме его сессии и напечатать выбранный вариант.

Нужна хукам: они запускаются системным python, а зависимости канала живут в venv
проекта, поэтому хук вызывает этот файл интерпретатором venv и читает stdout.

    ask_cli.py --session <id> --question "текст" --option "Да" --option "Нет"

Печатает выбранный вариант и выходит с кодом 0. Если сессия не привязана к теме
или ответа не было — код 2 и пустой stdout: вызывающий сам решает, что делать,
и обычно возвращается к обычному диалогу в терминале.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

import ask
import state

NO_CHANNEL = 2


def session_thread(session_id: str) -> int:
    path = state.state_dir() / "sessions" / f"{session_id}.json"
    if path.is_file() is False:
        sys.exit(NO_CHANNEL)
    return int(json.loads(path.read_text(encoding="utf-8"))["thread"])


def main() -> None:
    parser = argparse.ArgumentParser(description="спросить человека кнопками в Telegram")
    parser.add_argument("--session", required=True, help="id сессии Claude")
    parser.add_argument("--question", required=True, help="текст вопроса")
    parser.add_argument("--option", action="append", required=True, help="вариант ответа, можно повторять")
    parser.add_argument("--timeout", type=int, default=600, help="сколько секунд ждать ответа")
    args = parser.parse_args()

    load_dotenv(PROJECT_DIR / ".env")
    thread = session_thread(args.session)
    bot = ask.make_bot(os.environ["AI_PAIR_BOT_TOKEN"])
    chat_id = int(os.environ["AI_PAIR_CHAT_ID"])

    question_id = asyncio.run(ask.post_question(bot, chat_id, thread, args.question, args.option))
    try:
        print(ask.wait_answer(question_id, thread, args.timeout))
    except TimeoutError:
        sys.exit(NO_CHANNEL)


if __name__ == "__main__":
    main()
