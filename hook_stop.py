"""Хук Stop: сессия, привязанная к теме, не заканчивает ход молча.

Правило владельца: если сессия подключена к каналу, отчёт в тему обязателен в конце
ЛЮБОГО хода — неважно, пришла команда из Telegram или была набрана в терминале.
Человек видит работу только в теме, и ход, закончившийся без единого сообщения, для
него неотличим от зависшего агента.

Требование безусловное (решение владельца 15.09.2026): напоминание приходит в конце
КАЖДОГО хода, даже если сообщения по ходу уже уходили. Причина — отчёт нужен именно
завершающий: промежуточная реплика из середины работы не говорит человеку, чем ход
кончился. Непустой pending перечисляется в причине отказа поимённо.

Сессия не привязана к теме — хук молчит: работа в терминале без канала ломаться не
должна. Повторный вызов (`stop_hook_active`) тоже пропускается: напоминание приходит
один раз за ход, иначе сессия заперта навсегда.
"""

import json
import os
import sys
from pathlib import Path
from typing import NoReturn

PROJECT_DIR = Path(__file__).resolve().parent
GENERAL_LANE = "general"
LANE_VARIABLE = "AI_PAIR_LANE"
TOPIC_VARIABLE = "AI_PAIR_TOPIC"
sys.path.insert(0, str(PROJECT_DIR))

import state


def proceed(session_id: str) -> NoReturn:
    state.mark("stopped", session_id)
    sys.exit(0)


def lane_from_registry(topic: str) -> str:
    """Имя темы в номер: платформа знает имя при запуске, номер появляется при создании темы."""
    registry = state.state_dir() / "threads.json"
    if registry.is_file() is False:
        return ""
    thread = json.loads(registry.read_text(encoding="utf-8")).get(topic, 0)
    if thread > 0:
        return str(thread)
    return ""


def lane_from_environment() -> str:
    """Ленту задаёт запускающая сторона: переменная живёт ровно столько, сколько процесс."""
    lane = os.environ.get(LANE_VARIABLE, "").strip()
    if lane == GENERAL_LANE:
        return GENERAL_LANE
    topic = os.environ.get(TOPIC_VARIABLE, "").strip()
    if len(topic) > 0:
        return lane_from_registry(topic)
    return ""


def lane_from_binding(session_id: str) -> str:
    """Запасной путь для ручных запусков без платформы: привязку пишет bind.py."""
    path = state.state_dir() / "sessions" / f"{session_id}.json"
    if path.is_file() is False:
        return ""
    thread = int(json.loads(path.read_text(encoding="utf-8"))["thread"])
    if thread > 0:
        return str(thread)
    return GENERAL_LANE


def session_lane(session_id: str) -> str:
    """Ключ ленты сессии: номер темы или general — тот же, по которому пишет router."""
    lane = lane_from_environment()
    if len(lane) > 0:
        return lane
    lane = lane_from_binding(session_id)
    if len(lane) > 0:
        return lane
    proceed(session_id)


def name(waiting: object) -> str:
    """Сообщение чата зовётся номером, вводная из кода — местом, где владелец её написал."""
    if isinstance(waiting, int):
        return f"#{waiting}"
    return str(waiting)


def unanswered(lane: str) -> str:
    waiting = state.read_pending(lane)
    if len(waiting) == 0:
        return ""
    listed = ", ".join(name(item) for item in waiting)
    return f" Без ответа висят {listed} — на них ответь по существу."


def where(lane: str) -> tuple[str, str]:
    """Как назвать место в отказе и какой командой туда писать: у General флага нет."""
    if lane == GENERAL_LANE:
        return "General", ""
    return f"тему {lane}", f" --thread {lane}"


def block(lane: str) -> NoReturn:
    place, flag = where(lane)
    reply = PROJECT_DIR / "reply.py"
    reason = (
        f"Ход заканчивается — отчитайся в {place} ПОСЛЕДНИМ действием хода. "
        "Человек следит за работой оттуда, и реплика из середины работы не говорит ему, "
        "чем ход кончился. Это требуется каждый раз, даже если по ходу ты уже что-то писал. "
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
    block(lane)


if __name__ == "__main__":
    main()
