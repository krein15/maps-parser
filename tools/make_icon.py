r"""Собирает assets/icon.ico из иконки фирменного набора.

    .venv\Scripts\python tools\make_icon.py

Значок `>_` на тёмном фоне: он же стоит на ярлыке собранной программы.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "brand" / "icon-dark-512.png"
TARGET = ROOT / "assets" / "icon.ico"
SIZES = [(size, size) for size in (16, 24, 32, 48, 64, 128, 256)]


def main() -> int:
    if not SOURCE.exists():
        print(f"Нет картинки {SOURCE}", file=sys.stderr)
        return 1
    image = Image.open(SOURCE).convert("RGBA")
    image.save(TARGET, format="ICO", sizes=SIZES)
    print(f"Готово: {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
