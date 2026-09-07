"""MCP-сервер канала: ответ в тему задачи и привязка темы.

Поллинг Telegram живёт только в трее (router.py): getUpdates монопольный, а этот
сервер поднимается на каждую сессию — поэтому он умеет лишь отправлять и читать реестр.

Отправку и реестр берёт из соседних модулей, чтобы у CLI и MCP было одно поведение.
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP

import ask as asking
import bind as binding
import reply as replying

PROJECT_DIR = Path(__file__).resolve().parent

mcp = FastMCP("claude-telegram-chat")


@mcp.tool
def bind_task(name: str) -> int:
    """Вернуть message_thread_id темы задачи, создав тему при первом обращении.

    name — имя темы, принято `проект#задача`. Если тема уже существует в группе,
    сперва найди её id личным аккаунтом (list_topics) и передай через remember_task:
    ботом список тем получить нельзя.
    """
    load_dotenv(PROJECT_DIR / ".env")
    return binding.bind(name)


@mcp.tool
def remember_task(name: str, thread: int) -> int:
    """Запомнить уже найденную тему за задачей, ничего не создавая."""
    binding.remember(name, thread)
    return thread


@mcp.tool
def reply(thread: int, text: str) -> str:
    """Отправить сообщение в тему задачи. Длинный текст режется на части сам."""
    load_dotenv(PROJECT_DIR / ".env")
    asyncio.run(replying.send(thread, text, ""))
    return "отправлено"


@mcp.tool
def ask(thread: int, question: str, options: list[str], timeout_seconds: int = 1500) -> str:
    """Задать вопрос кнопками в тему задачи и дождаться выбора.

    Возвращает выбранный вариант. Свободный текст в теме тоже считается ответом:
    не всякий ответ укладывается в предложенные варианты.
    """
    load_dotenv(PROJECT_DIR / ".env")
    bot = asking.make_bot(os.environ["AI_PAIR_BOT_TOKEN"])
    chat_id = int(os.environ["AI_PAIR_CHAT_ID"])
    question_id = asyncio.run(asking.post_question(bot, chat_id, thread, question, options))
    return asking.wait_answer(question_id, thread, timeout_seconds)


if __name__ == "__main__":
    mcp.run()
