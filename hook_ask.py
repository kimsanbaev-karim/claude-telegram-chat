"""Хук PreToolUse: вопрос агента уходит в Telegram кнопками, ответ возвращается модели.

Claude Code показывает модели permissionDecisionReason при отказе — туда и подставляется
выбор. Приём тот же, что в старом мосте (ask_user.py): ответ человека инжектится
как результат инструмента через deny.

Тему берём по id сессии: её записывает bind при привязке. Нет привязки — хук молчит
и пропускает вопрос дальше, чтобы работа в терминале без канала не ломалась.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import NoReturn

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

import ask
import state

ANSWER_TIMEOUT_SECONDS = 1500
TOOL_NAME = "AskUserQuestion"


def allow() -> NoReturn:
    sys.exit(0)


def deny(reason: str) -> NoReturn:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(0)


def session_thread(session_id: str) -> int:
    path = state.state_dir() / "sessions" / f"{session_id}.json"
    if path.is_file() is False:
        allow()
    return int(json.loads(path.read_text(encoding="utf-8"))["thread"])


def first_question(tool_input: dict) -> tuple[str, list[str]]:
    question = tool_input["questions"][0]
    options = [option["label"] for option in question["options"]]
    return question["question"], options


def main() -> None:
    event = json.loads(sys.stdin.read())
    if event.get("tool_name") != TOOL_NAME:
        allow()

    load_dotenv(PROJECT_DIR / ".env")
    thread = session_thread(event["session_id"])
    text, options = first_question(event["tool_input"])

    bot = ask.make_bot(os.environ["AI_PAIR_BOT_TOKEN"])
    chat_id = int(os.environ["AI_PAIR_CHAT_ID"])
    question_id = asyncio.run(ask.post_question(bot, chat_id, thread, text, options))

    try:
        answer = ask.wait_answer(question_id, thread, ANSWER_TIMEOUT_SECONDS)
    except TimeoutError as error:
        deny(f"Вопрос ушёл в Telegram, но ответа нет: {error}. Спроси в терминале.")
    deny(f"Ответ из Telegram: {answer}")


if __name__ == "__main__":
    main()
