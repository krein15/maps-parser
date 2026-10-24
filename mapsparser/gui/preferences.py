"""Что окно помнит между запусками: город, нишу, объём сбора и папку отчётов."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from ..settings import user_data_dir

log = logging.getLogger(__name__)

SIZES = ("Быстро", "Обычно", "Весь город")
SIZE_LIMITS = {"Быстро": 60, "Обычно": 300, "Весь город": 1500}


@dataclass
class Preferences:
    city: str = ""
    query: str = ""
    size: str = "Обычно"
    sources: list[str] = field(default_factory=lambda: ["2gis", "yandex"])
    deep: bool = True  # открывать карточки 2ГИС ради почты
    only_without_site: bool = False
    delay: float = 1.5
    output_dir: str = ""
    open_report: bool = True
    use_cache: bool = True
    appearance: str = "Системная"

    @staticmethod
    def default_path() -> Path:
        return user_data_dir() / "window.json"

    @classmethod
    def load(cls, path: Path | None = None) -> Preferences:
        path = path or cls.default_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError):
            log.warning("Настройки окна в %s не читаются, беру значения по умолчанию", path)
            return cls()
        known = {item.name for item in fields(cls)}
        try:
            return cls(**{key: value for key, value in data.items() if key in known})
        except TypeError:
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or self.default_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")

    @property
    def limit(self) -> int:
        return SIZE_LIMITS.get(self.size, 300)
