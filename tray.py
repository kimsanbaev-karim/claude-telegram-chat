"""Трей-приложение канала Telegram ↔ Claude: держит router.py живым между сессиями.

Запуск без консоли: .venv/Scripts/pythonw.exe tray.py

Router должен быть ровно один на машину — отсюда single-instance mutex: getUpdates
монопольный, второй поллер того же токена получит Conflict.
"""

import os
import subprocess
import threading
import time
from pathlib import Path

import pystray
import win32api
import win32event
import winerror
from dotenv import load_dotenv

from icon import make_icon_image

PROJECT_DIR = Path(__file__).resolve().parent
LOG_PATH = PROJECT_DIR / "router.log"
MUTEX_NAME = "Global\\claude-telegram-chat-tray"
RESTART_DELAY_SECONDS = 5
POLL_SECONDS = 1.0
REQUIRED_ENV = ("AI_PAIR_BOT_TOKEN", "AI_PAIR_CHAT_ID", "AI_PAIR_ALLOWED_USERS")


def ensure_single_instance() -> None:
    win32event.CreateMutex(None, False, MUTEX_NAME)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        raise SystemExit("трей уже запущен — второй экземпляр поднимет Conflict у бота")


def check_env() -> None:
    missing = [name for name in REQUIRED_ENV if len(os.environ.get(name, "").strip()) == 0]
    if len(missing) > 0:
        raise SystemExit("не заданы переменные: " + ", ".join(missing) + " — проверь .env")


def stamp() -> str:
    return time.strftime("%H:%M:%S")


def write_log(message: str) -> None:
    with LOG_PATH.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"[трей {stamp()}] {message}\n")


class ProcessSupervisor:
    def __init__(self, name: str, command: list[str], workdir: Path) -> None:
        self.name = name
        self.command = command
        self.workdir = workdir
        self.stopping = threading.Event()
        self.process = self.spawn()
        threading.Thread(target=self.watch, daemon=True).start()

    def spawn(self) -> subprocess.Popen:
        write_log(f"запускаю {self.name}")
        log = LOG_PATH.open("a", encoding="utf-8", buffering=1)
        return subprocess.Popen(self.command, cwd=self.workdir, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)

    def watch(self) -> None:
        while self.stopping.is_set() is False:
            try:
                code = self.process.wait(timeout=POLL_SECONDS)
            except subprocess.TimeoutExpired:
                continue
            if self.stopping.is_set() is True:
                return
            write_log(f"{self.name} завершился с кодом {code}, перезапуск через {RESTART_DELAY_SECONDS} с")
            time.sleep(RESTART_DELAY_SECONDS)
            self.process = self.spawn()

    def restart(self) -> None:
        write_log("перезапуск по команде из меню")
        self.process.terminate()

    def stop(self) -> None:
        write_log("выход по команде из меню")
        self.stopping.set()
        self.process.terminate()


def start_supervisors() -> list[ProcessSupervisor]:
    router_python = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    router = [str(router_python), "-X", "utf8", str(PROJECT_DIR / "router.py")]
    return [ProcessSupervisor("router", router, PROJECT_DIR)]


def main() -> None:
    ensure_single_instance()
    load_dotenv(PROJECT_DIR / ".env")
    check_env()
    supervisors = start_supervisors()

    def on_open_log(icon, item) -> None:
        os.startfile(LOG_PATH)

    def on_restart(icon, item) -> None:
        for supervisor in supervisors:
            supervisor.restart()

    def on_quit(icon, item) -> None:
        for supervisor in supervisors:
            supervisor.stop()
        icon.stop()

    items = (
        pystray.MenuItem("Открыть лог", on_open_log),
        pystray.MenuItem("Перезапустить", on_restart),
        pystray.MenuItem("Выход", on_quit),
    )
    icon = pystray.Icon("claude-telegram-chat", make_icon_image(), "Канал Telegram ↔ Claude", pystray.Menu(*items))
    icon.run()


if __name__ == "__main__":
    main()
