"""Организации, как их отдают карты, и сведённая карточка фирмы.

Одна фирма приходит из каждого источника своим объектом `Company` — с собственным
идентификатором, рейтингом и набором контактов. `Place` — та же фирма после сведения:
общие поля плюс словарь «источник → что он про неё знает».
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Виды контактов. Порядок важен: в этом порядке контакты показываются в отчёте.
PHONE = "phone"
EMAIL = "email"
WEBSITE = "website"
VK = "vk"
TELEGRAM = "telegram"
WHATSAPP = "whatsapp"
INSTAGRAM = "instagram"
ODNOKLASSNIKI = "ok"
YOUTUBE = "youtube"
FACEBOOK = "facebook"
TWITTER = "twitter"
VIBER = "viber"
OTHER = "other"

LINK_KINDS: tuple[str, ...] = (
    PHONE,
    EMAIL,
    WEBSITE,
    VK,
    TELEGRAM,
    WHATSAPP,
    INSTAGRAM,
    ODNOKLASSNIKI,
    YOUTUBE,
    FACEBOOK,
    TWITTER,
    VIBER,
    OTHER,
)

LINK_TITLES: dict[str, str] = {
    PHONE: "Телефон",
    EMAIL: "Почта",
    WEBSITE: "Сайт",
    VK: "ВКонтакте",
    TELEGRAM: "Telegram",
    WHATSAPP: "WhatsApp",
    INSTAGRAM: "Instagram",
    ODNOKLASSNIKI: "Одноклассники",
    YOUTUBE: "YouTube",
    FACEBOOK: "Facebook",
    TWITTER: "Twitter",
    VIBER: "Viber",
    OTHER: "Другое",
}

# Соцсети и мессенджеры — всё, что не телефон, не почта и не сайт.
SOCIAL_KINDS: tuple[str, ...] = (
    VK,
    TELEGRAM,
    WHATSAPP,
    INSTAGRAM,
    ODNOKLASSNIKI,
    YOUTUBE,
    FACEBOOK,
    TWITTER,
    VIBER,
)


def host_of(url: str) -> str:
    """Имя хоста без схемы и «www»: по нему сайты из разных карт считаются одним."""
    rest = (url or "").split("://", 1)[-1]
    return rest.split("/", 1)[0].split("?", 1)[0].removeprefix("www.").lower()


def best_websites(values: tuple[str, ...]) -> tuple[str, ...]:
    """Один адрес на домен: http и https одного сайта — это один сайт, https важнее."""
    best: dict[str, str] = {}
    for value in values:
        host = host_of(value)
        if not host:
            continue
        current = best.get(host)
        if current is None or (value.startswith("https") and not current.startswith("https")):
            best[host] = value
    return tuple(best.values())


@dataclass(frozen=True)
class Link:
    """Контакт фирмы: вид, значение в пригодном для работы виде и исходная подпись."""

    kind: str
    value: str
    title: str = ""

    def __post_init__(self) -> None:
        if self.kind not in LINK_KINDS:
            raise ValueError(f"неизвестный вид контакта: {self.kind!r}")


@dataclass(frozen=True)
class Company:
    """Организация глазами одного источника."""

    source: str  # ключ источника: "2gis", "yandex"
    source_id: str  # идентификатор внутри источника
    name: str
    url: str = ""  # ссылка на карточку в источнике
    address: str = ""
    city: str = ""
    lat: float | None = None
    lon: float | None = None
    rubrics: tuple[str, ...] = ()
    rating: float | None = None
    reviews: int | None = None  # сколько оценок
    links: tuple[Link, ...] = ()
    schedule: str = ""
    branch_count: int | None = None
    verified_owner: bool | None = None  # владелец подтвердил карточку
    is_advert: bool = False  # место куплено рекламой
    photos: int | None = None
    detailed: bool = False  # открывали ли карточку, а не только выдачу
    collected_at: datetime | None = None

    def values(self, kind: str) -> tuple[str, ...]:
        """Значения контактов одного вида, в порядке появления, без повторов."""
        seen: dict[str, None] = {}
        for link in self.links:
            if link.kind == kind:
                seen.setdefault(link.value, None)
        return tuple(seen)

    @property
    def phones(self) -> tuple[str, ...]:
        return self.values(PHONE)

    @property
    def emails(self) -> tuple[str, ...]:
        return self.values(EMAIL)

    @property
    def websites(self) -> tuple[str, ...]:
        return best_websites(self.values(WEBSITE))

    @property
    def socials(self) -> tuple[Link, ...]:
        return tuple(link for link in self.links if link.kind in SOCIAL_KINDS)


@dataclass
class Place:
    """Фирма после сведения источников: одна строка отчёта."""

    name: str
    address: str = ""
    city: str = ""
    lat: float | None = None
    lon: float | None = None
    rubrics: tuple[str, ...] = ()
    by_source: dict[str, Company] = field(default_factory=dict)
    gaps: tuple[str, ...] = ()
    score: int = 0

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(self.by_source)

    @property
    def companies(self) -> tuple[Company, ...]:
        return tuple(self.by_source.values())

    def values(self, kind: str) -> tuple[str, ...]:
        """Контакты одного вида из всех источников, без повторов."""
        seen: dict[str, None] = {}
        for company in self.companies:
            for value in company.values(kind):
                seen.setdefault(value, None)
        return tuple(seen)

    @property
    def phones(self) -> tuple[str, ...]:
        return self.values(PHONE)

    @property
    def emails(self) -> tuple[str, ...]:
        return self.values(EMAIL)

    @property
    def websites(self) -> tuple[str, ...]:
        return best_websites(self.values(WEBSITE))

    @property
    def socials(self) -> tuple[Link, ...]:
        seen: dict[tuple[str, str], Link] = {}
        for company in self.companies:
            for link in company.socials:
                seen.setdefault((link.kind, link.value), link)
        return tuple(seen.values())

    @property
    def rating(self) -> float | None:
        """Средний рейтинг по источникам, которые его знают."""
        values = [c.rating for c in self.companies if c.rating]
        return round(sum(values) / len(values), 2) if values else None

    @property
    def reviews(self) -> int:
        """Оценки по всем источникам: у карт они считаются независимо, поэтому складываем."""
        return sum(c.reviews or 0 for c in self.companies)

    @property
    def schedule(self) -> str:
        for company in self.companies:
            if company.schedule:
                return company.schedule
        return ""

    @property
    def verified_owner(self) -> bool:
        return any(c.verified_owner for c in self.companies)

    def url(self, source: str) -> str:
        company = self.by_source.get(source)
        return company.url if company else ""
