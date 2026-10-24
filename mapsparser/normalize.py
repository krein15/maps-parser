"""Приведение контактов и названий к одному виду.

Две карты пишут одно и то же по-разному: «+7 (3452) 66‒67‒07» и «+73452666707»,
«oneraf-coffe.ru» и «http://link.2gis.ru/…?http://oneraf-coffe.ru», «Ола Ола, кофейня»
и «Ола Ола». Без общего вида фирма из 2ГИС и та же фирма из Яндекса не встретятся.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from .models import (
    EMAIL,
    FACEBOOK,
    INSTAGRAM,
    ODNOKLASSNIKI,
    OTHER,
    TELEGRAM,
    TWITTER,
    VIBER,
    VK,
    WEBSITE,
    WHATSAPP,
    YOUTUBE,
)

# Разные дефисы и пробелы, которыми карты разделяют цифры телефона.
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―­−"), "-")
_SPACES = dict.fromkeys(map(ord, "    "), " ")

_DIGITS_RE = re.compile(r"\d+")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-zА-Яа-я]{2,}$")
_UTM_RE = re.compile(r"^(utm_|yclid|gclid|ymclid|_openstat|from$|erid$)", re.I)

# Хозяин ссылки → вид контакта. Проверяется по концу имени хоста.
_SOCIAL_HOSTS: tuple[tuple[str, str], ...] = (
    ("vk.com", VK),
    ("vkontakte.ru", VK),
    ("vk.ru", VK),
    ("t.me", TELEGRAM),
    ("telegram.me", TELEGRAM),
    ("telegram.org", TELEGRAM),
    ("wa.me", WHATSAPP),
    ("whatsapp.com", WHATSAPP),
    ("instagram.com", INSTAGRAM),
    ("ok.ru", ODNOKLASSNIKI),
    ("odnoklassniki.ru", ODNOKLASSNIKI),
    ("youtube.com", YOUTUBE),
    ("youtu.be", YOUTUBE),
    ("rutube.ru", YOUTUBE),
    ("facebook.com", FACEBOOK),
    ("fb.com", FACEBOOK),
    ("twitter.com", TWITTER),
    ("x.com", TWITTER),
    ("viber.com", VIBER),
    ("viber.click", VIBER),
)

# Хосты-прокладки: сами по себе не сайт фирмы, настоящий адрес прячется внутри.
_REDIRECT_HOSTS = ("link.2gis.ru", "go.2gis.com", "redirect.appmetrica.yandex.com")


def phone(raw: str) -> str:
    """Телефон в виде +7XXXXXXXXXX. Пустая строка, если это не похоже на номер."""
    if not raw:
        return ""
    digits = "".join(_DIGITS_RE.findall(raw.translate(_DASHES)))
    if not digits:
        return ""
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10:
        return "+7" + digits
    if 11 <= len(digits) <= 15:
        return "+" + digits
    # Короткие номера (например, 2-66-67) встречаются в малых городах — оставляем как есть.
    return digits if len(digits) >= 5 else ""


def pretty_phone(value: str) -> str:
    """+73452666707 → +7 (3452) 66-67-07. Для российских номеров, остальные как есть."""
    if not value.startswith("+7") or len(value) != 12:
        return value
    rest = value[2:]
    return f"+7 ({rest[:3]}) {rest[3:6]}-{rest[6:8]}-{rest[8:]}"


def email(raw: str) -> str:
    """Почта в нижнем регистре. Пустая строка, если это не почта."""
    value = (raw or "").strip().strip("<>").translate(_SPACES).strip()
    if value.lower().startswith("mailto:"):
        value = value[7:]
    value = value.split("?", 1)[0].strip()
    return value.lower() if _EMAIL_RE.match(value) else ""


def unwrap_redirect(url: str) -> str:
    """Разворачивает счётчик переходов 2ГИС: link.2gis.ru/…?http://настоящий-сайт.ru."""
    if not url:
        return ""
    host = urlsplit(url if "//" in url else f"//{url}").netloc.lower()
    if not any(host.endswith(marker) for marker in _REDIRECT_HOSTS):
        return url
    tail = url.split("?", 1)[1] if "?" in url else ""
    if not tail:
        return url
    inner = unquote(tail)
    if inner.startswith(("http://", "https://")):
        return inner
    for _key, value in parse_qsl(tail):
        if value.startswith(("http://", "https://")):
            return value
    return url


def website(raw: str) -> str:
    """Адрес сайта без счётчиков, меток рекламы и хвостовой косой черты."""
    value = unwrap_redirect((raw or "").strip())
    if not value:
        return ""
    if "://" not in value:
        value = "http://" + value
    parts = urlsplit(value)
    host = parts.netloc.lower().removeprefix("www.")
    if not host or "." not in host:
        return ""
    query = "&".join(f"{k}={v}" for k, v in parse_qsl(parts.query) if not _UTM_RE.match(k))
    path = parts.path.rstrip("/")
    scheme = "https" if parts.scheme == "https" else "http"
    return urlunsplit((scheme, host, path, query, ""))


def domain(url: str) -> str:
    """Домен сайта без www — по нему сравниваем сайты из разных карт."""
    value = website(url)
    if not value:
        return ""
    return urlsplit(value).netloc.removeprefix("www.")


def social_kind(url: str) -> str:
    """Вид соцсети по адресу. OTHER, если хост незнакомый."""
    host = urlsplit(url if "//" in url else f"//{url}").netloc.lower().removeprefix("www.")
    for marker, kind in _SOCIAL_HOSTS:
        if host == marker or host.endswith("." + marker):
            return kind
    return OTHER


def classify_website(raw: str) -> tuple[str, str]:
    """Разбирает «сайт» на самом деле: карты часто кладут туда ссылку на телеграм или ВК.

    Возвращает вид контакта и значение; пустое значение — если разобрать не вышло.
    """
    address = unwrap_redirect((raw or "").strip())
    kind = social_kind(address)
    if kind != OTHER:
        return kind, address.split("?", 1)[0].strip()
    return WEBSITE, website(address)


def strip_city(address: str, city: str) -> str:
    """Убирает город из адреса: «ул. Ленина, 57, Тюмень» → «ул. Ленина, 57»."""
    value = clean_title(address)
    if not city:
        return value
    name = city.strip().lower().replace("ё", "е")
    parts = [p.strip() for p in value.split(",")]
    kept = [p for p in parts if p.lower().replace("ё", "е") != name]
    return ", ".join(kept) if kept else value


def link_value(kind: str, raw: str) -> str:
    """Значение контакта в общем виде — по виду контакта."""
    if kind == EMAIL:
        return email(raw)
    if kind == WEBSITE:
        return website(raw)
    if kind in (WHATSAPP, VIBER, TELEGRAM):
        # В мессенджерах номер важнее ссылки, но ссылка кликабельна — оставляем ссылку целиком,
        # обрезая приписанный текст сообщения.
        return raw.split("?", 1)[0].strip()
    return (raw or "").strip()


_NAME_TRASH_RE = re.compile(r"[«»\"'`“”„]+")
_NAME_SPACE_RE = re.compile(r"\s+")
# Приставки формы собственности: для сравнения названий они только мешают.
_LEGAL_FORMS = ("ооо", "оао", "зао", "пао", "ип", "ао", "нко", "ано", "мбу", "гбу", "муп", "гуп", "фгуп")


def name_key(name: str) -> str:
    """Название в виде, по которому фирмы из разных карт можно сравнить."""
    value = (name or "").lower().translate(_SPACES)
    value = value.split(",")[0]  # «Ола Ола, кофейня» → «ола ола»
    value = _NAME_TRASH_RE.sub("", value)
    value = value.replace("ё", "е")
    value = re.sub(r"[^\w\s-]", " ", value, flags=re.UNICODE)
    words = [w for w in _NAME_SPACE_RE.split(value) if w]
    while words and words[0] in _LEGAL_FORMS:
        words.pop(0)
    return " ".join(words).strip()


_HOUSE_RE = re.compile(r"\b(\d+[а-яa-z]?(?:\s*[/-]\s*\d+[а-яa-z]?)?)\b")
_STREET_WORDS = (
    "улица",
    "ул",
    "проспект",
    "пр-кт",
    "пр",
    "переулок",
    "пер",
    "бульвар",
    "б-р",
    "шоссе",
    "ш",
    "набережная",
    "наб",
    "площадь",
    "пл",
    "проезд",
    "тракт",
    "микрорайон",
    "мкр",
)


def address_key(address: str) -> str:
    """Улица и дом в сравнимом виде: «Советская ул., 55» и «улица Советская, 55» сойдутся."""
    value = (address or "").lower().translate(_SPACES).replace("ё", "е")
    value = value.replace(".", " ").replace(",", " ")
    words = [w for w in _NAME_SPACE_RE.split(value) if w and w not in _STREET_WORDS]
    text = " ".join(words)
    houses = _HOUSE_RE.findall(text)
    street = " ".join(w for w in words if not w[0].isdigit())
    house = houses[-1].replace(" ", "") if houses else ""
    return f"{street.strip()} {house}".strip()


def coordinates_key(lat: float | None, lon: float | None, precision: int = 4) -> str:
    """Координаты, округлённые до ~10 метров: одна и та же точка в двух картах чуть разная."""
    if lat is None or lon is None:
        return ""
    return f"{round(lat, precision)},{round(lon, precision)}"


def clean_title(name: str) -> str:
    """Название для отчёта: лишние пробелы убраны, кавычки оставлены как есть."""
    return _NAME_SPACE_RE.sub(" ", (name or "").translate(_SPACES)).strip()
