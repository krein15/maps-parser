"""Выгрузка в CSV — чтобы залить фирмы в CRM или в рассылку.

Разделитель — точка с запятой, кодировка — UTF-8 с BOM: так файл открывается
двойным щелчком в русском Excel и не превращается в кашу.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .models import LINK_TITLES, Place
from .normalize import pretty_phone
from .pipeline import Result

FIELDS = (
    "Фирма",
    "Чего нет",
    "Оценка",
    "Рубрика",
    "Адрес",
    "Город",
    "Телефон",
    "Мобильный",
    "Почта",
    "Сайт",
    "Что с сайтом",
    "Соцсети",
    "Рейтинг",
    "Оценок",
    "Режим работы",
    "Сеть",
    "ИНН",
    "В реестре с",
    "Источники",
    "Ссылка 2ГИС",
    "Ссылка Яндекс",
    "Широта",
    "Долгота",
)


def row_for(place: Place) -> list[str]:
    socials = "; ".join(f"{LINK_TITLES.get(link.kind, link.kind)}: {link.value}" for link in place.socials)
    return [
        place.name,
        ", ".join(place.gaps),
        str(place.score),
        ", ".join(place.rubrics[:3]),
        place.address,
        place.city,
        "; ".join(pretty_phone(value) for value in place.phones),
        "; ".join(pretty_phone(value) for value in place.mobile_phones),
        "; ".join(place.emails),
        "; ".join(place.websites),
        place.site.summary if place.site else "",
        socials,
        f"{place.rating:.1f}".replace(".", ",") if place.rating else "",
        str(place.reviews or ""),
        place.schedule,
        place.chain or ("" if place.branches <= 1 else f"{place.branches} точек"),
        place.entity.inn if place.entity else "",
        f"{place.entity.registered:%d.%m.%Y}" if place.entity and place.entity.registered else "",
        ", ".join(sorted(place.by_source)),
        place.url("2gis"),
        place.url("yandex"),
        f"{place.lat:.6f}".replace(".", ",") if place.lat else "",
        f"{place.lon:.6f}".replace(".", ",") if place.lon else "",
    ]


def write(result: Result, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(FIELDS)
        for place in result.places:
            writer.writerow(row_for(place))
    return path
