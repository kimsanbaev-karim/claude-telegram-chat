"""Хук Stop: сессия, привязанная к теме, не заканчивает ход молча.

Правило владельца: если сессия подключена к каналу, отчёт в тему обязателен в конце
ЛЮБОГО хода — неважно, пришла команда из Telegram или была набрана в терминале.
Человек видит работу только в теме, и ход, закончившийся без единого сообщения, для
него неотличим от зависшего агента.

Отчётом считается отправка через reply: она ставит отметку `reported` по теме. Ход
разрешается закончить, когда отметка свежее предыдущей остановки. Частный случай —
непустой pending: router пометил входящее «глазами», а ответа на него так и не было;
такие сообщения перечисляются в причине отказа поимённо.

Сессия не привязана к теме — хук молчит: работа в терминале без канала ломаться не
должна. Повторный вызов (`stop_hook_active`) тоже пропускается: напоминание приходит
один раз за ход, иначе сессия заперта навсегда.
"""

import json
import sys
from pathlib import Path
from typing import NoReturn

PROJECT_DIR = Path(__file__).resolve().parent
GENERAL_LANE = "general"
sys.path.insert(0, str(PROJECT_DIR))

import state


def proceed(session_id: str) -> NoReturn:
    state.mark("stopped", session_id)
    sys.exit(0)


def session_lane(session_id: str) -> str:
    """Ключ ленты сессии: номер темы или general — тот же, по которому пишет router."""
    path = state.state_dir() / "sessions" / f"{session_id}.json"
    if path.is_file() is False:
        proceed(session_id)
    thread = int(json.loads(path.read_text(encoding="utf-8"))["thread"])
    if thread > 0:
        return str(thread)
    return GENERAL_LANE


def unanswered(lane: str) -> str:
    waiting = state.read_pending(lane)
    if len(waiting) == 0:
        return ""
    listed = ", ".join(f"#{message_id}" for message_id in waiting)
    return f" Без ответа висят сообщения {listed} — на них ответь по существу."


def where(lane: str) -> tuple[str, str]:
    """Как назвать место в отказе и какой командой туда писать: у General флага нет."""
    if lane == GENERAL_LANE:
        return "General", ""
    return f"тему {lane}", f" --thread {lane}"


def block(lane: str) -> NoReturn:
    place, flag = where(lane)
    reply = PROJECT_DIR / "reply.py"
    reason = (
        f"Ход заканчивается, а в {place} за него не ушло ни одного сообщения. "
        "Человек следит за работой оттуда, и молчание для него неотличимо от зависшего агента. "
        f"Отчитайся: echo текст | python {reply}{flag}"
        f" — коротко, что сделано и что дальше.{unanswered(lane)}"
    )
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    sys.exit(0)


def main() -> None:
    event = json.loads(sys.stdin.read())
    session_id = event["session_id"]
    if event.get("stop_hook_active", False) is True:
        proceed(session_id)
    lane = session_lane(session_id)
    if state.mark_time("reported", lane) > state.mark_time("stopped", session_id):
        proceed(session_id)
    block(lane)


if __name__ == "__main__":
    main()
