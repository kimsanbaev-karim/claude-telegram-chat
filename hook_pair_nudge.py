"""Хук PostToolUse: вводная владельца не ждёт конца хода.

Решение владельца 14.09.2026. Stop-хук ловит молчание, но только когда ход уже закончился —
а в парном режиме владелец пишет комментарий в код и ждёт ответа СЕЙЧАС, посреди работы. Длинный
ход может идти десятки минут, и всё это время его вводная выглядит непрочитанной.

Наблюдатель кладёт каждую вводную в ту же очередь, где живут неотвеченные сообщения чата.
Этот хук после каждого инструмента смотрит очередь и, если в ней кто-то есть, напоминает
агенту ответить в тему. Напоминание идёт не чаще, чем раз в NUDGE_INTERVAL_SECONDS: иначе
оно повторялось бы на каждом вызове и превратилось бы в шум, который перестают читать.

Ответ через reply закрывает очередь целиком, и напоминания прекращаются сами.
"""

import json
import os
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
GENERAL_LANE = "general"
NUDGE_INTERVAL_SECONDS = 90.0
sys.path.insert(0, str(PROJECT_DIR))

import state


def lane_from_registry(topic: str) -> str:
    registry = state.state_dir() / "threads.json"
    if registry.is_file() is False:
        return ""
    thread = json.loads(registry.read_text(encoding="utf-8")).get(topic, 0)
    if thread > 0:
        return str(thread)
    return ""


def session_lane() -> str:
    lane = os.environ.get("AI_PAIR_LANE", "").strip()
    if lane == GENERAL_LANE:
        return GENERAL_LANE
    topic = os.environ.get("AI_PAIR_TOPIC", "").strip()
    if len(topic) == 0:
        return ""
    return lane_from_registry(topic)


def describe(waiting: list) -> str:
    return ", ".join(f"#{item}" if isinstance(item, int) else str(item) for item in waiting)


def main() -> None:
    lane = session_lane()
    if len(lane) == 0:
        return

    waiting = state.read_pending(lane)
    if len(waiting) == 0:
        return

    if time.time() - state.mark_time("nudged", lane) < NUDGE_INTERVAL_SECONDS:
        return
    state.mark("nudged", lane)

    flag = "" if lane == GENERAL_LANE else f" --thread {lane}"
    reply = PROJECT_DIR / "reply.py"
    answer = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"владелец ждёт ответа прямо сейчас, не в конце хода. Без ответа висят: {describe(waiting)}. "
                f"На каждое отвечай отдельно и цитатой, его слова не пересказывай — их видно в цитате. "
                f"Коротко: что сделал, что выяснил, что дальше: "
                f"python {reply}{flag} --reply-to <id> < файл-с-текстом"
            ),
        }
    }
    print(json.dumps(answer, ensure_ascii=False))


if __name__ == "__main__":
    main()
