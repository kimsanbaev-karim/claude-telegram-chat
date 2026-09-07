"""Хук PreToolUse: `git commit` подтверждается кнопками в Telegram, а не только в терминале.

Ставится на Bash. Команда с `git commit` уходит вопросом в тему сессии: «Коммитить?»
с двумя кнопками. Ответ «да» — коммит проходит, «нет» — отклоняется с этой причиной.

Канала нет, сессия не привязана или ответа не дождались — хук возвращает `ask`, то есть
обычный диалог подтверждения в терминале: мост не должен становиться единственной дверью.
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

PROJECT_DIR = Path(__file__).resolve().parent
CHANNEL_PYTHON = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
CHANNEL_CLI = PROJECT_DIR / "ask_cli.py"
ANSWER_TIMEOUT_SECONDS = 600
APPROVE = "Коммитить"
REJECT = "Не коммитить"
COMMIT_START = r"(?:^|[|;&(])\s*(?:cd\s+[^&|;]*&&\s*)?(?:[A-Za-z_]\w*=\S*\s+)*"
COMMIT_PATTERN = re.compile(COMMIT_START + r"git\s+commit(?!-)\b", re.IGNORECASE)
IN_TERMINAL = "git commit требует подтверждения. Покажи дифф и сообщение коммита и дождись ответа."


def decide(decision: str, reason: str) -> NoReturn:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(0)


def proceed() -> NoReturn:
    sys.exit(0)


def commits(command: str) -> bool:
    return len(COMMIT_PATTERN.findall(re.sub(r"\s+", " ", command).strip())) > 0


def ask_in_telegram(session_id: str, command: str) -> str:
    """Выбор человека кнопками. Пустая строка — канал недоступен, спрашиваем в терминале."""
    if CHANNEL_PYTHON.is_file() is False or len(session_id) == 0:
        return ""
    argv = [str(CHANNEL_PYTHON), "-X", "utf8", str(CHANNEL_CLI), "--session", session_id]
    argv += ["--question", f"Коммитить?\n\n{command[:600]}"]
    argv += ["--option", APPROVE, "--option", REJECT, "--timeout", str(ANSWER_TIMEOUT_SECONDS)]
    try:
        done = subprocess.run(argv, capture_output=True, timeout=ANSWER_TIMEOUT_SECONDS + 30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.decode("utf-8", "replace").strip()


def main() -> None:
    event = json.loads(sys.stdin.read())
    if event.get("tool_name", "") != "Bash":
        proceed()
    command = event.get("tool_input", {}).get("command", "")
    if commits(command) is False:
        proceed()
    answer = ask_in_telegram(event.get("session_id", ""), command)
    if answer == APPROVE:
        decide("allow", "Коммит подтверждён кнопкой в Telegram.")
    if answer == REJECT:
        decide("deny", "Коммит отклонён кнопкой в Telegram.")
    decide("ask", IN_TERMINAL)


if __name__ == "__main__":
    main()
