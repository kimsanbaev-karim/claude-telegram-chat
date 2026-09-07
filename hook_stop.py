"""Хук Stop: не отпускает ход, пока в теме висит сообщение без ответа.

Router помечает входящее «глазами» и кладёт его id в pending; reply снимает реакции,
когда ответ ушёл. Непустой pending на момент остановки означает ровно одно: человек
написал, а ход заканчивается молча — Telegram для него выглядит как проигнорированный.

Тему берём по id сессии, её записывает bind при привязке. Нет привязки — хук молчит:
работа в терминале без канала ломаться не должна.
"""

import json
import sys
from pathlib import Path
from typing import NoReturn

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

import state


def proceed() -> NoReturn:
    sys.exit(0)


def session_thread(session_id: str) -> int:
    path = state.state_dir() / "sessions" / f"{session_id}.json"
    if path.is_file() is False:
        proceed()
    return int(json.loads(path.read_text(encoding="utf-8"))["thread"])


def block(thread: int, waiting: list[int]) -> NoReturn:
    listed = ", ".join(f"#{message_id}" for message_id in waiting)
    reply = PROJECT_DIR / "reply.py"
    reason = (
        f"В теме {thread} остались без ответа сообщения {listed}. "
        f"Ответь туда: echo текст | python {reply} --thread {thread} --reply-to {waiting[-1]} — "
        "отправка снимет «глаза», и ход закончится. Ответ по существу: что сделано и что дальше."
    )
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    sys.exit(0)


def main() -> None:
    event = json.loads(sys.stdin.read())
    if event.get("stop_hook_active", False) is True:
        proceed()
    thread = session_thread(event["session_id"])
    waiting = state.read_pending(str(thread))
    if len(waiting) == 0:
        proceed()
    block(thread, waiting)


if __name__ == "__main__":
    main()
