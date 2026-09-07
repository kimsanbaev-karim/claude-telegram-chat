"""Общие пути состояния канала и учёт сообщений, на которые ещё не ответили.

Router помечает входящее реакцией «глаза» и кладёт его id сюда; reply снимает
реакции со всех накопленных, когда ответ ушёл. Файл на тему, потому что темы
живут независимо друг от друга.
"""

import json
import os
from pathlib import Path


def state_dir() -> Path:
    return Path(os.environ.get("AI_PAIR_STATE_DIR", Path.home() / ".claude-telegram-chat"))


def pending_path(thread: str) -> Path:
    path = state_dir() / "pending"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{thread}.json"


def add_pending(thread: str, message_id: int) -> None:
    path = pending_path(thread)
    waiting = read_pending(thread)
    waiting.append(message_id)
    path.write_text(json.dumps(waiting), encoding="utf-8")


def read_pending(thread: str) -> list[int]:
    path = pending_path(thread)
    if path.is_file() is True:
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def take_pending(thread: str) -> list[int]:
    waiting = read_pending(thread)
    pending_path(thread).write_text("[]", encoding="utf-8")
    return waiting
