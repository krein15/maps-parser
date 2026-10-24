"""Кэш страниц на диске.

Нужен ради трёх вещей: не дёргать карты повторно, когда сбор перезапускают;
собирать фикстуры для тестов; разбираться, что именно пришло, когда формат поменяется.
Страницы жмутся gzip — сырой HTML 2ГИС весит около мегабайта, Яндекса полтора.
"""

from __future__ import annotations

import gzip
import hashlib
import time
from pathlib import Path


class Cache:
    """Ответы страниц в каталоге, по файлу на адрес."""

    def __init__(self, directory: Path, ttl_hours: float = 24.0) -> None:
        self.directory = Path(directory)
        self.ttl_seconds = ttl_hours * 3600

    def path_for(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return self.directory / f"{digest}.html.gz"

    def get(self, url: str) -> str | None:
        path = self.path_for(url)
        if not path.exists():
            return None
        if self.ttl_seconds and time.time() - path.stat().st_mtime > self.ttl_seconds:
            return None
        try:
            return gzip.decompress(path.read_bytes()).decode("utf-8")
        except (OSError, gzip.BadGzipFile, UnicodeDecodeError):
            return None

    def put(self, url: str, text: str) -> None:
        path = self.path_for(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Пишем через временный файл: прерванный сбор не должен оставить обрезанную страницу.
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(gzip.compress(text.encode("utf-8"), 6))
        temporary.replace(path)

    def clear(self) -> int:
        """Удаляет все страницы. Возвращает, сколько удалено."""
        if not self.directory.exists():
            return 0
        removed = 0
        for path in self.directory.glob("*.html.gz"):
            path.unlink(missing_ok=True)
            removed += 1
        return removed

    def size_mb(self) -> float:
        if not self.directory.exists():
            return 0.0
        total = sum(p.stat().st_size for p in self.directory.glob("*.html.gz"))
        return round(total / 1024 / 1024, 1)
