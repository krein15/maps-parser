"""Сведение одной и той же фирмы из разных карт в одну строку.

Правило намеренно строгое: объединяем, только если совпало название **и** место —
адрес или координаты в пределах полутора сотен метров. Соблазн слить по телефону
или по сайту велик, но у сетевой кофейни на весь город один сайт и часто один номер:
сольёшь — и шесть точек превратятся в одну, а отчёт станет враньём.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from .models import Company, Place
from .normalize import address_key, clean_title, name_key

# Две карты ставят точку одной и той же фирмы с разбросом в десятки метров;
# соседние заведения в одном здании отстоят дальше.
SAME_PLACE_METERS = 150.0


def distance_meters(first: Company, second: Company) -> float | None:
    """Расстояние между организациями по координатам."""
    if None in (first.lat, first.lon, second.lat, second.lon):
        return None
    lat1, lon1, lat2, lon2 = first.lat, first.lon, second.lat, second.lon
    mean_lat = math.radians((lat1 + lat2) / 2)
    dx = (lon2 - lon1) * 111_320 * math.cos(mean_lat)
    dy = (lat2 - lat1) * 110_540
    return math.hypot(dx, dy)


def same_place(first: Company, second: Company) -> bool:
    """Одна ли это фирма. Название обязательно, место — адресом или координатами."""
    if first.source == second.source:
        return False  # внутри одной карты филиалы уже разведены
    first_name, second_name = name_key(first.name), name_key(second.name)
    if not first_name or first_name != second_name:
        return False
    first_address, second_address = address_key(first.address), address_key(second.address)
    if first_address and first_address == second_address:
        return True
    distance = distance_meters(first, second)
    if distance is not None and distance <= SAME_PLACE_METERS:
        return True
    # Ни адреса, ни координат — последняя зацепка — общий телефон.
    if not first_address and not second_address and distance is None:
        return bool(set(first.phones) & set(second.phones))
    return False


class _Groups:
    """Система непересекающихся множеств по индексам организаций."""

    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, index: int) -> int:
        while self._parent[index] != index:
            self._parent[index] = self._parent[self._parent[index]]
            index = self._parent[index]
        return index

    def union(self, first: int, second: int) -> None:
        a, b = self.find(first), self.find(second)
        if a != b:
            self._parent[b] = a


def merge(companies: Iterable[Company]) -> list[Place]:
    """Собирает список организаций всех карт в список фирм."""
    items = list(companies)
    groups = _Groups(len(items))

    buckets: dict[str, list[int]] = {}
    for index, company in enumerate(items):
        buckets.setdefault(name_key(company.name), []).append(index)

    for key, indexes in buckets.items():
        if not key or len(indexes) < 2:
            continue
        for position, first in enumerate(indexes):
            for second in indexes[position + 1 :]:
                if same_place(items[first], items[second]):
                    groups.union(first, second)

    collected: dict[int, list[Company]] = {}
    for index, company in enumerate(items):
        collected.setdefault(groups.find(index), []).append(company)

    return [place_from(group) for group in collected.values()]


def place_from(group: list[Company]) -> Place:
    """Собирает фирму из её карточек в разных картах."""
    # Названия у карт разной длины: «Ола Ола» и «Ола Ола, кофейня». Берём то, что длиннее,
    # но без типа после запятой — он уже учтён в рубриках.
    name = clean_title(max((c.name for c in group), key=len))
    with_address = [c for c in group if c.address]
    address = max((c.address for c in with_address), key=len) if with_address else ""
    city = next((c.city for c in group if c.city), "")
    latitudes = [c.lat for c in group if c.lat is not None]
    longitudes = [c.lon for c in group if c.lon is not None]
    rubrics: dict[str, None] = {}
    for company in group:
        for rubric in company.rubrics:
            rubrics.setdefault(rubric, None)
    return Place(
        name=name,
        address=address,
        city=city,
        lat=round(sum(latitudes) / len(latitudes), 6) if latitudes else None,
        lon=round(sum(longitudes) / len(longitudes), 6) if longitudes else None,
        rubrics=tuple(rubrics),
        by_source={company.source: company for company in group},
    )
