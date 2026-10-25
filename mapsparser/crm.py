"""Выгрузка под импорт в CRM.

Обычный отчёт читает человек, а CRM — машина: ей нужны свои названия колонок и
по одному значению в клетке. Поэтому для amoCRM и Битрикс24 файлы делаются
отдельно, а не «переименуйте шапку сами».

Что важно для импорта: первый телефон и первая почта идут в свои колонки (CRM
обычно берёт из клетки одно значение), а всё остальное — в примечание, чтобы
менеджер видел, с чем заходить, прямо в карточке.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .models import LINK_TITLES, Place
from .normalize import pretty_phone
from .pipeline import Result


@dataclass(frozen=True)
class Format:
    """Как CRM называет колонки, которые нам нужны."""

    key: str
    title: str
    columns: tuple[str, ...]
    delimiter: str = ";"


AMO = Format(
    key="amo",
    title="amoCRM",
    columns=("Название компании", "Телефон", "Email", "Веб-сайт", "Адрес", "Примечание", "Теги"),
)
BITRIX = Format(
    key="bitrix",
    title="Битрикс24",
    columns=("Название", "Телефон", "E-mail", "Сайт", "Адрес", "Комментарий", "Отрасль"),
)
FORMATS: tuple[Format, ...] = (AMO, BITRIX)


def note_for(place: Place) -> str:
    """Примечание в карточке: с чем заходить и что ещё известно."""
    parts: list[str] = []
    if place.gaps:
        parts.append("Чего нет: " + ", ".join(place.gaps))
    if place.site and not place.site.alive:
        parts.append(f"Сайт: {place.site.summary}")
    if place.rating:
        parts.append(f"Рейтинг {place.rating} ({place.reviews} оценок)")
    if place.schedule:
        parts.append(place.schedule)
    extra_phones = place.phones[1:]
    if extra_phones:
        parts.append("Ещё телефоны: " + ", ".join(pretty_phone(value) for value in extra_phones))
    extra_emails = place.emails[1:]
    if extra_emails:
        parts.append("Ещё почты: " + ", ".join(extra_emails))
    if place.socials:
        parts.append(
            "Соцсети: " + ", ".join(f"{LINK_TITLES.get(link.kind, link.kind)} {link.value}" for link in place.socials)
        )
    if place.entity and place.entity.inn:
        registered = f", в реестре с {place.entity.registered:%d.%m.%Y}" if place.entity.registered else ""
        parts.append(f"ИНН {place.entity.inn}{registered}")
    links = [place.url(key) for key in sorted(place.by_source) if place.url(key)]
    if links:
        parts.append("Карточки: " + " ".join(links))
    return ". ".join(parts)


def tags_for(place: Place) -> str:
    """Метки, по которым в CRM удобно фильтровать список обзвона."""
    tags = [place.city] if place.city else []
    if place.rubrics:
        tags.append(place.rubrics[0])
    if not place.websites:
        tags.append("без сайта")
    elif place.site and not place.site.alive:
        tags.append("сайт не работает")
    if place.score >= 60:
        tags.append("горячий")
    return ", ".join(tags)


def row_for(place: Place) -> list[str]:
    return [
        place.name,
        pretty_phone(place.phones[0]) if place.phones else "",
        place.emails[0] if place.emails else "",
        place.websites[0] if place.websites else "",
        ", ".join(part for part in (place.city, place.address) if part),
        note_for(place),
        tags_for(place),
    ]


def write(result: Result, path: Path, crm: Format = AMO) -> Path:
    """Пишет файл под импорт. UTF-8 с BOM: обе CRM так открывают кириллицу правильно."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=crm.delimiter, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(crm.columns)
        for place in result.places:
            writer.writerow(row_for(place))
    return path


def by_key(key: str) -> Format:
    for crm in FORMATS:
        if crm.key == key:
            return crm
    known = ", ".join(item.key for item in FORMATS)
    raise KeyError(f"неизвестная CRM {key!r}; есть: {known}")


def write_all(result: Result, directory: Path, stem: str) -> list[Path]:
    """Делает по файлу на каждую CRM рядом с отчётом."""
    return [write(result, directory / f"{stem} — {crm.title}.csv", crm) for crm in FORMATS]
