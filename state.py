"""Общие пути состояния канала и учёт сообщений, на которые ещё не ответили.

Router помечает входящее реакцией «глаза» и кладёт его id сюда; reply снимает
реакции со всех накопленных, когда ответ ушёл. Файл на тему, потому что темы
живут независимо друг от друга.
"""

import json
import os
import time
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


def marks_dir(name: str) -> Path:
    path = state_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def mark(name: str, key: str) -> None:
    """Отметить событие текущим временем: отчёт ушёл, ход закончился."""
    payload = json.dumps({"at": time.time()})
    (marks_dir(name) / f"{key}.json").write_text(payload, encoding="utf-8")


def mark_time(name: str, key: str) -> float:
    """Когда событие случилось в последний раз; ноль — не случалось никогда."""
    path = marks_dir(name) / f"{key}.json"
    if path.is_file() is False:
        return 0.0
    return float(json.loads(path.read_text(encoding="utf-8"))["at"])
