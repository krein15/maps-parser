"""Сайт фирмы как третий источник.

Карты отдают телефон почти всем, а почту — меньше чем трети: в пробном сборе по Тюмени
сайт был у 31 фирмы из 44, а почта только у 14. Почта этих семнадцати никуда не делась —
она лежит на их собственном сайте, в подвале или на странице «Контакты».

Поэтому программа заходит на найденный сайт и забирает оттуда почту и телефоны. Заодно
смотрит на сам сайт, и это оказывается ценнее контактов: «сайта нет» — слабый повод для
разговора, а «сайт есть, но он не открывается», «сайт без защищённого соединения» или
«сайт не открывается на телефоне» — уже предметный. Человеку не надо продавать идею
сайта: ему надо показать, что он платит за неработающий.

Правило вежливости: не больше двух запросов на сайт — главная страница и, если на ней
почты не нашлось, страница контактов.
"""

from __future__ import annotations

import re
from datetime import datetime

from .http import Fetcher, FetchError
from .models import SiteReport
from .normalize import email as clean_email
from .normalize import phone as clean_phone

MAX_PAGES_PER_SITE = 2
CHECK_TIMEOUT = 10.0

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_MAILTO_RE = re.compile(r'mailto:([^"\'>\s?]+)', re.I)
_TEL_RE = re.compile(r'tel:([+0-9\s()\-]{6,})', re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_VIEWPORT_RE = re.compile(r'<meta[^>]+name=["\']?viewport', re.I)
_FORM_RE = re.compile(r"<form[\s>]", re.I)
_INPUT_RE = re.compile(r'<(?:input[^>]+type=["\']?(?:tel|email)|textarea)', re.I)
_CONTACTS_LINK_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(?:(?!</a>).){0,80}?'
    r"(?:контакт|contacts?|связ[аь]|написать)",
    re.I | re.S,
)

# Виджеты заявок и чатов: форма может быть не в разметке, а подгружаться скриптом.
_WIDGETS = (
    "jivosite", "jivo.ru", "bitrix24", "carrotquest", "talk-me", "envybox",
    "callibri", "verbox", "chatra", "marquiz", "tilda-forms", "flexbe",
    "amocrm", "calltouch", "comagic", "mango-office",
)

# Домены, которые встречаются в разметке, но почтой фирмы не являются.
_JUNK_EMAIL_HOSTS = (
    "example.com", "example.ru", "domain.com", "sentry.io", "w3.org", "schema.org",
    "googleapis.com", "gstatic.com", "jquery.com", "bootstrapcdn.com", "wixpress.com",
    "sentry.wixpress.com", "your-site.ru", "mail.example", "site.ru", "test.ru",
)
_JUNK_EMAIL_NAMES = ("noreply", "no-reply", "postmaster", "abuse", "webmaster@localhost")

# Признаки заглушки хостера вместо сайта.
_PARKED_MARKERS = (
    "домен припаркован", "сайт не настроен", "домен продаётся", "домен продается",
    "this domain is for sale", "parked domain", "coming soon", "страница в разработке",
    "сайт в разработке", "купить домен", "域名",
)


def _clean_html(html: str) -> str:
    """Выкидывает скрипты и стили: в них полно адресов, которые почтой фирмы не являются."""
    without = re.sub(r"<script\b.*?</script>", " ", html, flags=re.S | re.I)
    return re.sub(r"<style\b.*?</style>", " ", without, flags=re.S | re.I)


def _looks_like_firm_email(value: str) -> bool:
    if not value:
        return False
    name, _, host = value.partition("@")
    if any(host == junk or host.endswith("." + junk) for junk in _JUNK_EMAIL_HOSTS):
        return False
    if name in _JUNK_EMAIL_NAMES:
        return False
    # «logo@2x.png», «icon@3x.svg» — вёрстка, а не почта
    return not re.search(r"\.(png|jpe?g|gif|svg|webp|css|js)$", value, re.I)


def emails_from(html: str) -> tuple[str, ...]:
    """Почты со страницы: сперва из ссылок mailto, потом из текста."""
    found: dict[str, None] = {}
    for raw in _MAILTO_RE.findall(html):
        value = clean_email(raw)
        if _looks_like_firm_email(value):
            found.setdefault(value, None)
    text = _clean_html(html)
    for raw in _EMAIL_RE.findall(text):
        value = clean_email(raw)
        if _looks_like_firm_email(value):
            found.setdefault(value, None)
    return tuple(found)


def phones_from(html: str) -> tuple[str, ...]:
    """Телефоны со страницы — только из ссылок tel: в тексте слишком много чисел."""
    found: dict[str, None] = {}
    for raw in _TEL_RE.findall(html):
        value = clean_phone(raw)
        if value:
            found.setdefault(value, None)
    return tuple(found)


def title_of(html: str) -> str:
    match = _TITLE_RE.search(html)
    if not match:
        return ""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", match.group(1)))
    return text.strip()[:200]


def is_parked(html: str, title: str) -> bool:
    haystack = (title + " " + _clean_html(html)[:4000]).lower()
    if any(marker in haystack for marker in _PARKED_MARKERS):
        return True
    if len(re.sub(r"<[^>]+>", " ", _clean_html(html)).split()) >= 15:
        return False
    # Текста почти нет. Это заглушка, только если на странице нет и ничего рабочего:
    # у одностраничника на картинках вполне может быть форма и почта, и он живой.
    return not has_form(html) and not emails_from(html) and not phones_from(html)


def has_form(html: str) -> bool:
    if _FORM_RE.search(html) and _INPUT_RE.search(html):
        return True
    lowered = html.lower()
    return any(widget in lowered for widget in _WIDGETS)


def contacts_link(html: str, base_url: str) -> str:
    """Ссылка на страницу контактов, если она есть на главной."""
    from urllib.parse import urljoin, urlsplit

    for href in _CONTACTS_LINK_RE.findall(html):
        if href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        target = urljoin(base_url, href)
        if urlsplit(target).netloc == urlsplit(base_url).netloc:
            return target
    return ""


def check(url: str, fetcher: Fetcher) -> SiteReport:
    """Открывает сайт и возвращает всё, что удалось про него выяснить."""
    now = datetime.now().astimezone()
    try:
        page = fetcher.probe(url, timeout=CHECK_TIMEOUT)
    except FetchError as exc:
        return SiteReport(url=url, error=str(exc), checked_at=now, pages=1)

    if not page.ok:
        return SiteReport(
            url=url, status=page.status, final_url=page.url, checked_at=now, pages=1,
            error=f"ответ {page.status}",
        )

    html = page.text
    title = title_of(html)
    emails = emails_from(html)
    phones = phones_from(html)
    pages = 1

    if not emails and pages < MAX_PAGES_PER_SITE:
        link = contacts_link(html, page.url)
        if link:
            try:
                contacts = fetcher.probe(link, timeout=CHECK_TIMEOUT)
                pages += 1
                if contacts.ok:
                    emails = emails_from(contacts.text)
                    phones = phones or phones_from(contacts.text)
            except FetchError:
                pass  # не открылась страница контактов — не беда, главная уже разобрана

    return SiteReport(
        url=url,
        reachable=True,
        status=page.status,
        final_url=page.url,
        https=page.url.lower().startswith("https://"),
        mobile=bool(_VIEWPORT_RE.search(html)),
        form=has_form(html),
        parked=is_parked(html, title),
        title=title,
        emails=emails,
        phones=phones,
        pages=pages,
        checked_at=now,
    )
