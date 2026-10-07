"""Хвост ленты одной темы для Monitor: каждая новая строка ленты становится одним событием.

    python -X utf8 follow.py --thread 42

Сначала печатает непрочитанное — то, на что сессия ещё не ответила: платформа поднимает инстанс
по факту сообщения, и оно уже лежит в ленте. Дальше — только то, что пришло после запуска.
Строка ушла в сессию — на исходное сообщение ставятся «глаза»: значок означает «агент увидел»,
а не «роутер принял», иначе при мёртвом наблюдателе он врёт.

Две машины: AI_PAIR_FOLLOW_DIR=delivered — читать не ленту бота, а ленту, которую платформа
наполняет только адресованными этой машине сообщениями.
"""

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

import state

PROJECT_DIR = Path(__file__).resolve().parent
POLL_SECONDS = 1.0
SEEN_REACTION = [{"type": "emoji", "emoji": "👀"}]
REACTION_TIMEOUT_SECONDS = 10


def lane_path(thread: str) -> Path:
    return state.state_dir() / os.environ.get("AI_PAIR_FOLLOW_DIR", "inbox") / f"{thread}.jsonl"


def unread(path: Path, thread: str) -> list[dict]:
    waiting = set(state.read_pending(thread))
    if len(waiting) == 0 or path.is_file() is False:
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if len(line.strip()) > 0]
    return [entry for entry in map(json.loads, lines) if entry.get("message_id") in waiting]


def describe(entry: dict) -> str:
    sender = f" от {entry['from_bot']}" if "from_bot" in entry else ""
    parts = [f"[ai-pair #{entry['message_id']}{sender}] {entry['text']}"]
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


def mark_seen(message_id: int) -> None:
    """Глаза ставятся ПОСЛЕ печати строки: наблюдатель — единственный, кто знает, что событие дошло до сессии."""
    token = os.environ.get("AI_PAIR_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("AI_PAIR_CHAT_ID", "").strip()
    if len(token) == 0 or len(chat_id) == 0:
        return

    body = json.dumps({"chat_id": int(chat_id), "message_id": message_id, "reaction": SEEN_REACTION})
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/setMessageReaction",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=REACTION_TIMEOUT_SECONDS).read()
    except (urllib.error.URLError, OSError, ValueError):
        # Реакция — украшение: её отказ не должен убивать наблюдателя, иначе канал замолкает целиком.
        return


def follow(path: Path, thread: str) -> None:
    offset = start_offset(path)
    for entry in unread(path, thread):
        print(describe(entry), flush=True)
        mark_seen(int(entry["message_id"]))
    while path.is_file() is False:
        time.sleep(POLL_SECONDS)
    with path.open("r", encoding="utf-8") as lane:
        lane.seek(offset)
        while True:
            raw = lane.readline()
            if len(raw.strip()) == 0:
                time.sleep(POLL_SECONDS)
                continue
            entry = json.loads(raw.strip())
            print(describe(entry), flush=True)
            mark_seen(int(entry["message_id"]))


def start_offset(path: Path) -> int:
    if path.is_file() is True:
        return path.stat().st_size
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="следить за лентой темы для Monitor")
    parser.add_argument("--thread", required=True, help="ключ ленты: message_thread_id темы проекта или general")
    args = parser.parse_args()
    load_dotenv(PROJECT_DIR / ".env")
    follow(lane_path(args.thread), args.thread)


if __name__ == "__main__":
    main()
