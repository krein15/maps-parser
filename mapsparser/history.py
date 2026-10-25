"""Память о прошлых сборах и разбор изменений.

Один сбор — это снимок ниши на сегодня. Ценность появляется на втором: видно,
кто в нише появился, у кого наконец завёлся сайт, у кого он умер, где просел
рейтинг. Новая фирма — самый горячий лид из возможных: сайта у неё ещё нет,
отзывов нет, и прямо сейчас кто-то решает, где это всё заказывать.

Фирма опознаётся по названию и адресу, а не по номеру в карте: карта может
потерять карточку или отдать её под другим идентификатором, а фирма на месте.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .models import Place
from .normalize import address_key, coordinates_key, name_key
from .settings import user_data_dir

RATING_STEP = 0.2  # меньшая разница — это шум, а не изменение
REVIEWS_JUMP = 10  # заметный прирост отзывов


def place_key(place: Place) -> str:
    """Устойчивый ключ фирмы: название плюс место."""
    name = name_key(place.name)
    where = address_key(place.address) or coordinates_key(place.lat, place.lon)
    return f"{name}|{where}"


def run_key(city_alias: str, query: str) -> str:
    """Ключ сбора: город и ниша. По нему и ведётся история."""
    clean = "".join(ch if ch.isalnum() or ch in " -_" else "" for ch in query.lower().replace("ё", "е"))
    tail = clean.strip().replace(" ", "_")
    return f"{city_alias}-{tail}" if tail else city_alias


@dataclass
class Snapshot:
    """Что было известно про фирму в прошлый раз."""

    name: str = ""
    address: str = ""
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    websites: list[str] = field(default_factory=list)
    socials: int = 0
    rating: float | None = None
    reviews: int = 0
    site_alive: bool | None = None
    sources: list[str] = field(default_factory=list)
    score: int = 0
    first_seen: str = ""
    last_seen: str = ""


def snapshot_of(place: Place, *, first_seen: str = "", now: str = "") -> Snapshot:
    stamp = now or datetime.now().astimezone().isoformat(timespec="seconds")
    return Snapshot(
        name=place.name,
        address=place.address,
        emails=list(place.emails),
        phones=list(place.phones),
        websites=list(place.websites),
        socials=len(place.socials),
        rating=place.rating,
        reviews=place.reviews,
        site_alive=place.site.alive if place.site else None,
        sources=sorted(place.by_source),
        score=place.score,
        first_seen=first_seen or stamp,
        last_seen=stamp,
    )


@dataclass(frozen=True)
class Change:
    """Одно изменение по одной фирме."""

    kind: str
    title: str
    place: Place | None = None
    was: str = ""
    now: str = ""
    name: str = ""
    address: str = ""

    @property
    def text(self) -> str:
        who = self.name or (self.place.name if self.place else "")
        detail = f" ({self.was} → {self.now})" if self.was or self.now else ""
        return f"{who}: {self.title}{detail}"


@dataclass
class Changes:
    """Разбор того, что поменялось с прошлого сбора."""

    first_run: bool = False
    previous_at: str = ""
    items: list[Change] = field(default_factory=list)

    @property
    def new(self) -> list[Change]:
        return [change for change in self.items if change.kind == "new"]

    def of(self, kind: str) -> list[Change]:
        return [change for change in self.items if change.kind == kind]

    def __bool__(self) -> bool:
        return bool(self.items)


class History:
    """Файл истории по одной нише одного города."""

    def __init__(self, key: str, directory: Path | None = None) -> None:
        self.key = key
        self.directory = directory or (user_data_dir() / "history")
        self.path = self.directory / f"{key}.json"

    def load(self) -> tuple[dict[str, Snapshot], str]:
        """Прошлый снимок и когда он был сделан."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}, ""
        places = {}
        for key, value in (raw.get("places") or {}).items():
            known = {field_name: value[field_name] for field_name in Snapshot.__annotations__ if field_name in value}
            places[key] = Snapshot(**known)
        return places, str(raw.get("updated", ""))

    def save(self, places: list[Place], *, previous: dict[str, Snapshot] | None = None) -> None:
        previous = previous or {}
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        snapshots = {}
        for place in places:
            key = place_key(place)
            was = previous.get(key)
            snapshots[key] = snapshot_of(place, first_seen=was.first_seen if was else "", now=now)
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "key": self.key,
            "updated": now,
            "places": {key: asdict(value) for key, value in snapshots.items()},
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    def forget(self) -> bool:
        if self.path.exists():
            self.path.unlink()
            return True
        return False


def compare(places: list[Place], previous: dict[str, Snapshot], previous_at: str = "") -> Changes:
    """Сравнивает сегодняшний сбор с прошлым."""
    if not previous:
        return Changes(first_run=True)

    changes = Changes(previous_at=previous_at)
    seen: set[str] = set()
    for place in places:
        key = place_key(place)
        seen.add(key)
        was = previous.get(key)
        if was is None:
            changes.items.append(
                Change("new", "новая фирма в нише", place, name=place.name, address=place.address)
            )
            continue
        changes.items.extend(_compare_one(place, was))

    for key, was in previous.items():
        if key not in seen:
            changes.items.append(
                Change("gone", "пропала из выдачи", None, name=was.name, address=was.address)
            )
    return changes


def _compare_one(place: Place, was: Snapshot) -> list[Change]:
    found: list[Change] = []
    name, address = place.name, place.address

    if place.websites and not was.websites:
        found.append(Change("got_site", "появился сайт", place, now=place.websites[0], name=name, address=address))
    elif was.websites and not place.websites:
        found.append(Change("lost_site", "сайт пропал с карты", place, was=was.websites[0], name=name, address=address))

    if place.emails and not was.emails:
        found.append(Change("got_email", "появилась почта", place, now=place.emails[0], name=name, address=address))

    if was.phones and not place.phones:
        found.append(Change("lost_phone", "пропал телефон", place, was=was.phones[0], name=name, address=address))

    if place.site is not None and was.site_alive is not None:
        if was.site_alive and not place.site.alive:
            found.append(Change("site_died", "сайт перестал открываться", place, name=name, address=address))
        elif not was.site_alive and place.site.alive:
            found.append(Change("site_revived", "сайт снова работает", place, name=name, address=address))

    if place.rating is not None and was.rating is not None:
        difference = place.rating - was.rating
        if difference <= -RATING_STEP:
            found.append(
                Change("rating_down", "рейтинг просел", place, was=f"{was.rating}", now=f"{place.rating}",
                       name=name, address=address)
            )
        elif difference >= RATING_STEP:
            found.append(
                Change("rating_up", "рейтинг вырос", place, was=f"{was.rating}", now=f"{place.rating}",
                       name=name, address=address)
            )

    if place.reviews - was.reviews >= REVIEWS_JUMP:
        found.append(
            Change("reviews_jump", "прибавилось отзывов", place, was=f"{was.reviews}", now=f"{place.reviews}",
                   name=name, address=address)
        )
    return found


def summary(changes: Changes) -> str:
    """Короткая строка для журнала и для Telegram."""
    if changes.first_run:
        return "Это первый сбор по нише — сравнивать не с чем, запомнил на будущее."
    if not changes:
        return "С прошлого раза в нише ничего не изменилось."
    parts = []
    for kind, word in (
        ("new", "новых"),
        ("gone", "пропало"),
        ("got_site", "обзавелись сайтом"),
        ("site_died", "сайт умер"),
        ("got_email", "появилась почта"),
        ("rating_down", "рейтинг просел"),
    ):
        count = len(changes.of(kind))
        if count:
            parts.append(f"{word}: {count}")
    return "Изменения с прошлого сбора — " + ", ".join(parts) if parts else "Мелкие изменения в нише."
