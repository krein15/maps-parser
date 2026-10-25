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


def is_mobile(phone_value: str) -> bool:
    """Мобильный ли номер: в России это +79…. По таким можно писать в мессенджер."""
    return phone_value.startswith("+79") and len(phone_value) == 12


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
class SiteReport:
    """Что выяснилось про сайт фирмы, когда программа на него зашла.

    Живёт здесь, а не рядом с проверкой: проверка опирается на нормализацию контактов,
    а та — на эти же модели, и общий тип данных не должен замыкать круг импортов.
    """

    url: str
    reachable: bool = False
    status: int | None = None
    final_url: str = ""
    https: bool = False
    mobile: bool = False  # есть мета viewport — сайт свёрстан под телефон
    form: bool = False  # есть форма заявки или виджет чата
    parked: bool = False  # заглушка хостера вместо сайта
    title: str = ""
    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    error: str = ""
    pages: int = 0
    checked_at: datetime | None = None

    @property
    def alive(self) -> bool:
        """Сайт открылся и это действительно сайт, а не заглушка."""
        return self.reachable and not self.parked

    @property
    def summary(self) -> str:
        """Короткая строка для отчёта: что с сайтом не так."""
        if not self.reachable:
            return f"не открывается ({self.error or self.status})"
        if self.parked:
            return "заглушка вместо сайта"
        notes = []
        if not self.https:
            notes.append("без https")
        if not self.mobile:
            notes.append("не для телефона")
        if not self.form:
            notes.append("без формы заявки")
        return ", ".join(notes) if notes else "в порядке"


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
    branch_count: int | None = None  # сколько точек у фирмы в городе
    chain: str = ""  # название сети, если точка в неё входит
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
    extra: tuple[Link, ...] = ()  # контакты, найденные не на картах, а на сайте фирмы
    site: SiteReport | None = None
    gaps: tuple[str, ...] = ()
    score: int = 0

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(self.by_source)

    @property
    def companies(self) -> tuple[Company, ...]:
        return tuple(self.by_source.values())

    def values(self, kind: str) -> tuple[str, ...]:
        """Контакты одного вида из всех источников и с сайта фирмы, без повторов."""
        seen: dict[str, None] = {}
        for company in self.companies:
            for value in company.values(kind):
                seen.setdefault(value, None)
        for link in self.extra:
            if link.kind == kind:
                seen.setdefault(link.value, None)
        return tuple(seen)

    def from_site(self, kind: str) -> tuple[str, ...]:
        """Контакты, которых на картах не было, — их нашли на сайте фирмы."""
        on_maps = {value for company in self.companies for value in company.values(kind)}
        return tuple(link.value for link in self.extra if link.kind == kind and link.value not in on_maps)

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
        from_maps = tuple(link for company in self.companies for link in company.socials)
        for link in (*from_maps, *self.extra):
            if link.kind in SOCIAL_KINDS:
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

    @property
    def chain(self) -> str:
        """Название сети, если точка в неё входит."""
        for company in self.companies:
            if company.chain:
                return company.chain
        return ""

    @property
    def branches(self) -> int:
        """Сколько точек у этой фирмы в городе по данным карт."""
        return max((c.branch_count or 0) for c in self.companies) if self.companies else 0

    @property
    def is_chain(self) -> bool:
        """Сетевая точка: звонить в филиал бессмысленно, решает центр."""
        return bool(self.chain) or self.branches > 1

    @property
    def mobile_phones(self) -> tuple[str, ...]:
        return tuple(value for value in self.phones if is_mobile(value))

    def url(self, source: str) -> str:
        company = self.by_source.get(source)
        return company.url if company else ""
