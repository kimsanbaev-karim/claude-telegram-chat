"""Кадры из видео: агент читает картинки, но не ролики.

Видео, гифка и кружочек превращаются в несколько равномерных кадров — по ним видно,
что происходит, и каждый кадр агент открывает обычным чтением файла.

Нужен ffmpeg в PATH. Его нет — вызывающий получает исключение и пишет об этом
в ленту: молчаливая потеря вложения хуже явной ошибки.
"""

import subprocess
from pathlib import Path

FFMPEG_TIMEOUT_SECONDS = 120
DEFAULT_FRAME_COUNT = 6
FRAME_QUALITY = "3"


def duration_seconds(video: Path) -> float:
    argv = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)]
    done = subprocess.run(argv, capture_output=True, timeout=FFMPEG_TIMEOUT_SECONDS)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.decode("utf-8", "replace").strip()[:300])
    return float(done.stdout.decode("utf-8", "replace").strip())


def extract_frames(video: Path, out_dir: Path, count: int = DEFAULT_FRAME_COUNT) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    total = duration_seconds(video)
    step = total / (count + 1)
    frames = []
    for index in range(1, count + 1):
        target = out_dir / f"{video.stem}-{index:02d}.jpg"
        moment = f"{step * index:.3f}"
        argv = ["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", moment, "-i", str(video)]
        argv += ["-frames:v", "1", "-q:v", FRAME_QUALITY, "-y", str(target)]
        done = subprocess.run(argv, capture_output=True, timeout=FFMPEG_TIMEOUT_SECONDS)
        if done.returncode != 0:
            raise RuntimeError(done.stderr.decode("utf-8", "replace").strip()[:300])
        frames.append(target)
    return frames
