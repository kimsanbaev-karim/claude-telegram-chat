"""Ярлык автозапуска трея в папке «Автозагрузка».

Создать ярлык: запусти этот файл интерпретатором из venv без аргументов.
Убрать ярлык: запусти его же с флагом --remove.

Ярлык создаётся через COM (pywin32), а не PowerShell: имя содержит кириллицу,
а argv PowerShell на Windows приходит в ANSI и портит её.
"""

import argparse
from pathlib import Path

import win32com.client

PROJECT_DIR = Path(__file__).resolve().parent
SHORTCUT_NAME = "Канал Telegram-Claude (трей).lnk"


def startup_dir() -> Path:
    shell = win32com.client.Dispatch("WScript.Shell")
    return Path(shell.SpecialFolders("Startup"))


def shortcut_path() -> Path:
    return startup_dir() / SHORTCUT_NAME


def create() -> None:
    target = PROJECT_DIR / ".venv" / "Scripts" / "pythonw.exe"
    if target.is_file() is False:
        raise SystemExit(f"нет интерпретатора {target} — сначала создай venv")
    shell = win32com.client.Dispatch("WScript.Shell")
    link = shell.CreateShortcut(str(shortcut_path()))
    link.TargetPath = str(target)
    link.Arguments = "tray.py"
    link.WorkingDirectory = str(PROJECT_DIR)
    link.Description = "Канал между Telegram и сессиями Claude Code"
    link.Save()
    print(f"ярлык создан: {shortcut_path()}")


def remove() -> None:
    path = shortcut_path()
    if path.is_file() is True:
        path.unlink()
        print(f"ярлык удалён: {path}")
        return
    print(f"ярлыка не было: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="автозапуск трея канала")
    parser.add_argument("--remove", action="store_true", help="убрать ярлык из автозагрузки")
    args = parser.parse_args()
    if args.remove is True:
        remove()
        return
    create()


if __name__ == "__main__":
    main()
