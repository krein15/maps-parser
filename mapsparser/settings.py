"""Где программа держит свои файлы."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Maps Parser"
APP_TITLE = "Карты Парсер"
BRAND = "kreinstudio"


def user_data_dir() -> Path:
    """Рабочий каталог программы: кэш страниц и найденные города."""
    base = os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share"
    path = Path(base) / APP_NAME.replace(" ", "")
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_cache_dir() -> Path:
    return user_data_dir() / "cache"


def default_output_dir() -> Path:
    """Куда складываются отчёты: «Документы\\Карты Парсер»."""
    return Path.home() / "Documents" / APP_TITLE


def settings_file() -> Path:
    return user_data_dir() / "settings.json"
