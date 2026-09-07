"""Значок канала: круг из двух половин — логотип Claude слева, Telegram справа.

Логотипы скачиваются один раз в служебную папку рядом с лентами и кешируются:
в репозитории бинарников нет. Нет сети при первом запуске — рисуется запасной
значок из двух цветных половин, и об этом пишется в stderr.

В трее значок виден размером 16×16, поэтому формы крупные и без мелких деталей:
на таком размере читается только контраст половин и силуэт в центре.
"""

import os
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
CLAUDE_URL = "https://claude.ai/images/claude_app_icon.png"
TELEGRAM_URL = "https://telegram.org/img/t_logo.png"
CLAUDE_COLOR = (217, 119, 87)
TELEGRAM_COLOR = (42, 171, 238)
DOWNLOAD_TIMEOUT_SECONDS = 20
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) claude-telegram-chat"


def assets_dir() -> Path:
    state_dir = Path(os.environ.get("AI_PAIR_STATE_DIR", Path.home() / ".claude-telegram-chat"))
    path = state_dir / "assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def fetch(url: str, target: Path) -> Path:
    if target.is_file() is True:
        return target
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        target.write_bytes(response.read())
    return target


def half_mask(left: bool) -> Image.Image:
    mask = Image.new("L", (SIZE, SIZE), 0)
    draw = ImageDraw.Draw(mask)
    start = 90 if left is True else 270
    draw.pieslice((0, 0, SIZE - 1, SIZE - 1), start=start, end=start + 180, fill=255)
    return mask


def fallback_image() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.pieslice((0, 0, SIZE - 1, SIZE - 1), start=90, end=270, fill=CLAUDE_COLOR)
    draw.pieslice((0, 0, SIZE - 1, SIZE - 1), start=270, end=450, fill=TELEGRAM_COLOR)
    return image


def compose() -> Image.Image:
    assets = assets_dir()
    claude = Image.open(fetch(CLAUDE_URL, assets / "claude.png")).convert("RGBA").resize((SIZE, SIZE))
    telegram = Image.open(fetch(TELEGRAM_URL, assets / "telegram.png")).convert("RGBA").resize((SIZE, SIZE))
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    image.paste(claude, (0, 0), half_mask(left=True))
    image.paste(telegram, (0, 0), half_mask(left=False))
    return image


def make_icon_image() -> Image.Image:
    try:
        return compose()
    except OSError as error:
        sys.stderr.write(f"значок: логотипы недоступны ({error}), рисую запасной\n")
        return fallback_image()


def main() -> None:
    make_icon_image().save("icon.png")
    print("значок сохранён: icon.png")


if __name__ == "__main__":
    main()
