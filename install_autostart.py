"""Ярлык автозапуска трея в папке «Автозагрузка» и, по желанию, на рабочем столе.

Создать ярлык: запусти этот файл интерпретатором из venv без аргументов.
Положить такой же на рабочий стол: флаг --desktop.
Убрать ярлык: запусти его же с флагом --remove (убирает из обоих мест).

Ярлык на столе нужен не для красоты: трей, поднятый из сессии агента, живёт её
потомком и умирает вместе с ней, а запущенный кликом — потомок оболочки, и
переживает и сессии, и чистку фоновых задач.

Ярлык создаётся через COM (pywin32), а не PowerShell: имя содержит кириллицу,
а argv PowerShell на Windows приходит в ANSI и портит её.
"""

import argparse
from pathlib import Path

import win32com.client

PROJECT_DIR = Path(__file__).resolve().parent
SHORTCUT_NAME = "Канал Telegram-Claude (трей).lnk"


def special_folder(name: str) -> Path:
    shell = win32com.client.Dispatch("WScript.Shell")
    return Path(shell.SpecialFolders(name))


def shortcut_path(folder: str) -> Path:
    return special_folder(folder) / SHORTCUT_NAME


def create(folder: str) -> None:
    target = PROJECT_DIR / ".venv" / "Scripts" / "pythonw.exe"
    if target.is_file() is False:
        raise SystemExit(f"нет интерпретатора {target} — сначала создай venv")
    shell = win32com.client.Dispatch("WScript.Shell")
    link = shell.CreateShortcut(str(shortcut_path(folder)))
    link.TargetPath = str(target)
    link.Arguments = "tray.py"
    link.WorkingDirectory = str(PROJECT_DIR)
    link.Description = "Канал между Telegram и сессиями Claude Code"
    link.Save()
    print(f"ярлык создан: {shortcut_path(folder)}")


def remove(folder: str) -> None:
    path = shortcut_path(folder)
    if path.is_file() is True:
        path.unlink()
        print(f"ярлык удалён: {path}")
        return
    print(f"ярлыка не было: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="автозапуск трея канала")
    parser.add_argument("--remove", action="store_true", help="убрать ярлык из автозагрузки и с рабочего стола")
    parser.add_argument("--desktop", action="store_true", help="положить ярлык ещё и на рабочий стол")
    args = parser.parse_args()
    folders = ["Startup", "Desktop"] if args.desktop is True or args.remove is True else ["Startup"]
    for folder in folders:
        if args.remove is True:
            remove(folder)
            continue
        create(folder)


if __name__ == "__main__":
    main()
