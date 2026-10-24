"""Список карт, с которыми работает программа.

Встроенные источники объявляют себя здесь, сторонние приходят точкой входа
`mapsparser.sources`: поставил пакет — и его карта появилась в окне, во флагах
командной строки и в колонках отчёта, без единой правки в ядре.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from .base import Collector, Report, SearchRequest, Source
from .twogis import TwoGis
from .yandex import Yandex

BUILTIN: tuple[Source, ...] = (TwoGis, Yandex)

ENTRY_POINT_GROUP = "mapsparser.sources"


def _external() -> list[Source]:
    found: list[Source] = []
    try:
        points = entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:  # старые версии importlib.metadata
        return found
    for point in points:
        try:
            source = point.load()
        # Чужой пакет не должен ронять программу: не загрузился — просто не появится в списке.
        except Exception:
            continue
        if isinstance(source, Source):
            found.append(source)
    return found


def all_sources() -> list[Source]:
    """Все доступные карты: встроенные, затем подключённые пакетами."""
    seen: dict[str, Source] = {source.key: source for source in BUILTIN}
    for source in _external():
        seen.setdefault(source.key, source)
    return list(seen.values())


def source_keys() -> list[str]:
    return [source.key for source in all_sources()]


def get(key: str) -> Source:
    for source in all_sources():
        if source.key == key:
            return source
    known = ", ".join(source_keys())
    raise KeyError(f"неизвестный источник {key!r}; есть: {known}")


def resolve(keys: list[str] | tuple[str, ...] | None) -> list[Source]:
    """Карты по ключам; пустой список — значит все."""
    if not keys:
        return all_sources()
    return [get(key) for key in keys]


__all__ = [
    "BUILTIN",
    "Collector",
    "Report",
    "SearchRequest",
    "Source",
    "TwoGis",
    "Yandex",
    "all_sources",
    "get",
    "resolve",
    "source_keys",
]
