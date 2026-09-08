"""Хвост ленты одной темы для Monitor: каждая новая строка ленты становится одним событием.

    python -X utf8 follow.py --thread 42

Печатает только то, что пришло ПОСЛЕ запуска: старая переписка событиями не считается.
"""

import argparse
import json
import os
import time
from pathlib import Path

POLL_SECONDS = 1.0


def lane_path(thread: str) -> Path:
    state_dir = Path(os.environ.get("AI_PAIR_STATE_DIR", Path.home() / ".claude-telegram-chat"))
    return state_dir / "inbox" / f"{thread}.jsonl"


def describe(raw: str) -> str:
    entry = json.loads(raw)
    parts = [f"[ai-pair #{entry['message_id']}] {entry['text']}"]
    if "reply_to" in entry:
        parts.append(f"| в ответ на #{entry['reply_to']}")
    if "media" in entry:
        parts.append(f"| файл: {entry['media']}")
    if "frames" in entry:
        frames = entry["frames"]
        parts.append(f"| кадры ({len(frames)} шт.): {Path(frames[0]).parent}")
    if "error" in entry:
        parts.append(f"| ОШИБКА: {entry['error']}")
    return " ".join(parts)


def start_offset(path: Path) -> int:
    if path.is_file() is True:
        return path.stat().st_size
    return 0


def follow(path: Path) -> None:
    offset = start_offset(path)
    while path.is_file() is False:
        time.sleep(POLL_SECONDS)
    with path.open("r", encoding="utf-8") as lane:
        lane.seek(offset)
        while True:
            raw = lane.readline()
            if len(raw.strip()) == 0:
                time.sleep(POLL_SECONDS)
                continue
            print(describe(raw.strip()), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="следить за лентой темы для Monitor")
    parser.add_argument("--thread", required=True, help="ключ ленты: message_thread_id темы проекта или general")
    args = parser.parse_args()
    follow(lane_path(args.thread))


if __name__ == "__main__":
    main()
