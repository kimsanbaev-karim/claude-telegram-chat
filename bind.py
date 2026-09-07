"""Привязка задачи к теме форума: отдаёт message_thread_id, создавая тему при первом обращении.

Имя темы задаёт вызывающий — принято `проект#задача`, чтобы одинаковые id задач
в разных проектах не схлопывались в одну тему.

В Bot API нет метода получить список тем (есть только create/edit/close/reopen/delete),
поэтому БОТОМ найти существующую тему по имени нельзя — id хранится в реестре
AI_PAIR_STATE_DIR/threads.json. Искать тему по имени умеет личный аккаунт через
telegram-MCP (list_topics) — это делает скилл перед вызовом bind и передаёт готовый id.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Bot
from telegram.request import HTTPXRequest

PROJECT_DIR = Path(__file__).resolve().parent
CONNECT_TIMEOUT = 20.0
READ_TIMEOUT = 30.0
POOL_TIMEOUT = 20.0


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if len(value) == 0:
        raise SystemExit(f"bind: переменная {name} не задана — привязывать нечем")
    return value


def registry_path() -> Path:
    state_dir = Path(os.environ.get("AI_PAIR_STATE_DIR", Path.home() / ".claude-telegram-chat"))
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "threads.json"


def load_registry(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_registry(path: Path, registry: dict) -> None:
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def create_topic(name: str) -> int:
    client = HTTPXRequest(connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT, pool_timeout=POOL_TIMEOUT)
    bot = Bot(require_env("AI_PAIR_BOT_TOKEN"), request=client)
    chat_id = int(require_env("AI_PAIR_CHAT_ID"))
    async with bot:
        topic = await bot.create_forum_topic(chat_id, name=name)
    return topic.message_thread_id


def remember(name: str, thread_id: int) -> None:
    path = registry_path()
    registry = load_registry(path)
    registry[name] = thread_id
    save_registry(path, registry)


def attach_session(session_id: str, thread_id: int) -> None:
    path = registry_path().parent / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"thread": thread_id}, ensure_ascii=False)
    (path / f"{session_id}.json").write_text(payload, encoding="utf-8")


def bind(name: str) -> int:
    registry = load_registry(registry_path())
    if name in registry:
        return int(registry[name])
    thread_id = asyncio.run(create_topic(name))
    remember(name, thread_id)
    return thread_id


def main() -> None:
    parser = argparse.ArgumentParser(description="получить message_thread_id темы задачи")
    parser.add_argument("--name", required=True, help="имя темы, принято `проект#задача`")
    parser.add_argument("--thread", type=int, default=0, help="уже найденный id темы: только запомнить его")
    parser.add_argument("--session", default="", help="id сессии Claude: привязать её к теме для хука вопросов")
    args = parser.parse_args()
    load_dotenv(PROJECT_DIR / ".env")
    thread_id = args.thread
    if thread_id > 0:
        remember(args.name, thread_id)
    else:
        thread_id = bind(args.name)
    if len(args.session) > 0:
        attach_session(args.session, thread_id)
    print(thread_id)


if __name__ == "__main__":
    main()
