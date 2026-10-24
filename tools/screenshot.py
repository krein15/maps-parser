r"""Снимок окна для README и для проверки вёрстки.

    .venv\Scripts\python tools\screenshot.py docs\screenshots\app-search.png light Поиск

Вкладка «Результаты» наполняется фирмами из сохранённых страниц (tests/fixtures),
поэтому снимок делается без сети и всегда одинаковый. Контакты в фикстурах
выдуманы — в открытый репозиторий настоящие не попадают.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import customtkinter as ctk
import window_capture
from demo_data import CITY, demo_result

from mapsparser.gui.app import App
from mapsparser.gui.widgets import set_entry


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots" / "app.png"
    mode = sys.argv[2] if len(sys.argv) > 2 else "light"
    tab = sys.argv[3] if len(sys.argv) > 3 else "Поиск"

    app = App()
    app.appearance.set("Светлая" if mode == "light" else "Тёмная")
    app._set_appearance("Светлая" if mode == "light" else "Тёмная")
    set_entry(app.city, CITY.name)
    set_entry(app.query, "кофейня")
    app._show_places(demo_result())
    app.tabs.set(tab)

    def shoot() -> None:
        app.update_idletasks()
        window_capture.save(app, target)
        print(f"Снимок: {target}")
        app.destroy()

    app.after(1200, shoot)
    app.mainloop()
    return 0


if __name__ == "__main__":
    ctk.set_default_color_theme("blue")
    raise SystemExit(main())
