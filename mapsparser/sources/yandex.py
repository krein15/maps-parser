"""Яндекс Карты: выдача поиска и карточка организации.

Страница тоже собирается на сервере, но состояние лежит иначе — в самом большом
теге `<script type="application/json">` (около полутора мегабайт). Результаты —
в `stack[0].results.items`.

Яндекс устроен противоположно 2ГИС: в выдаче **сразу есть контакты** — телефон,
сайт, соцсети, рейтинг, часы работы и даже сколько у фирмы фотографий. Двадцать пять
организаций за один запрос. Чего у Яндекса нет никогда — это почты: её не публикуют
ни в выдаче, ни в карточке.

Город не нужно превращать в код: достаточно дописать его название к запросу.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime
from typing import Any
from urllib.parse import quote

from ..cities import City
from ..http import FetchError
from ..models import (
    FACEBOOK,
    INSTAGRAM,
    ODNOKLASSNIKI,
    PHONE,
    TELEGRAM,
    TWITTER,
    VIBER,
    VK,
    WEBSITE,
    WHATSAPP,
    YOUTUBE,
    Company,
    Link,
)
from ..normalize import classify_website, clean_title, phone, social_kind, strip_city
from .base import Collector, Report, SearchRequest, Source

KEY = "yandex"
SITE = "https://yandex.ru/maps"
PAGE_SIZE = 25
MAX_PAGES = 60  # 1500 организаций: дальше выдача обычно повторяется

_STATE_RE = re.compile(r'<script type="application/json"[^>]*>(.*?)</script>', re.S)
_ORG_TYPE = "business"

# Как Яндекс зовёт соцсети в socialLinks.
_SOCIAL_TYPES = {
    "vkontakte": VK,
    "vk": VK,
    "telegram": TELEGRAM,
    "whatsapp": WHATSAPP,
    "instagram": INSTAGRAM,
    "odnoklassniki": ODNOKLASSNIKI,
    "youtube": YOUTUBE,
    "facebook": FACEBOOK,
    "twitter": TWITTER,
    "viber": VIBER,
}


def parse_state(html: str) -> dict[str, Any]:
    """Состояние страницы Яндекс Карт — самый большой блок JSON в документе."""
    best = ""
    for match in _STATE_RE.finditer(html):
        if len(match.group(1)) > len(best):
            best = match.group(1)
    if not best:
        raise FetchError("Яндекс: состояние страницы не найдено — похоже, формат сайта изменился")
    try:
        return json.loads(best)
    except json.JSONDecodeError as exc:
        raise FetchError(f"Яндекс: состояние страницы не разобрать ({exc})") from exc


def results_of(state: dict[str, Any]) -> dict[str, Any]:
    """Блок выдачи: сами организации и счётчики."""
    for frame in state.get("stack") or []:
        if isinstance(frame, dict) and isinstance(frame.get("results"), dict):
            return frame["results"]
    return {}


def links_from(item: dict[str, Any]) -> tuple[Link, ...]:
    """Телефоны, сайт и соцсети организации в общем виде."""
    links: list[Link] = []
    for entry in item.get("phones") or []:
        if not isinstance(entry, dict) or entry.get("type") not in (None, "phone"):
            continue
        value = phone(entry.get("value") or entry.get("number", ""))
        if value:
            links.append(Link(PHONE, value, clean_title(entry.get("number", "")) or value))
    for raw in item.get("urls") or []:
        # Яндекс кладёт в «сайт» и ссылки на соцсети — смотрим на хост, а не на название поля.
        kind, value = classify_website(raw)
        if value:
            links.append(Link(kind, value, value))
    for entry in item.get("socialLinks") or []:
        if not isinstance(entry, dict):
            continue
        href = (entry.get("href") or "").split("?", 1)[0].strip()
        if not href.startswith("http"):
            continue
        kind = _SOCIAL_TYPES.get(entry.get("type", ""), "") or social_kind(href)
        links.append(Link(kind, href, clean_title(entry.get("readableHref", "")) or href))
    for entry in item.get("businessLinks") or []:
        if not isinstance(entry, dict):
            continue
        href = (entry.get("href") or "").split("?", 1)[0].strip()
        if href.startswith("http"):
            links.append(Link(social_kind(href), href, href))
    return tuple(links)


def company_from(item: dict[str, Any], city: City) -> Company | None:
    """Организация из элемента выдачи Яндекса. None — если это подборка или не организация."""
    if item.get("type") != _ORG_TYPE:
        return None
    name = clean_title(item.get("title", ""))
    identifier = str(item.get("id") or "")
    if not name or not identifier:
        return None
    coordinates = item.get("coordinates") or []
    lon, lat = [*coordinates, None, None][:2]  # Яндекс отдаёт долготу первой
    rating = (item.get("ratingData") or {}).get("ratingValue")
    reviews = (item.get("ratingData") or {}).get("ratingCount")
    properties = item.get("businessProperties") or {}
    photos = (item.get("photos") or {}).get("count")
    seoname = item.get("seoname") or "org"
    return Company(
        source=KEY,
        source_id=identifier,
        name=name,
        url=f"{SITE}/org/{seoname}/{identifier}/",
        address=strip_city(item.get("address", "") or item.get("fullAddress", ""), city.name),
        city=city.name,
        lat=float(lat) if lat is not None else None,
        lon=float(lon) if lon is not None else None,
        rubrics=tuple(
            clean_title(c.get("name", ""))
            for c in (item.get("categories") or [])
            if isinstance(c, dict) and c.get("name")
        ),
        rating=round(float(rating), 1) if rating else None,
        reviews=int(reviews) if reviews else None,
        links=links_from(item),
        schedule=clean_title(item.get("workingTimeText", "")),
        branch_count=None,
        chain=clean_title((item.get("chain") or {}).get("name", "")),
        verified_owner=bool(properties.get("has_verified_owner")) if properties else None,
        is_advert=bool(item.get("advert") or item.get("direct")),
        photos=int(photos) if photos else None,
        detailed=True,  # контакты есть уже в выдаче
        collected_at=datetime.now().astimezone(),
    )


def _in_city(item: dict[str, Any], city: City) -> bool:
    """Отсеивает соседние города: поиск по тексту иногда уезжает за границу города."""
    address = (item.get("fullAddress") or "").lower().replace("ё", "е")
    if not address:
        return True
    name = city.name.lower().replace("ё", "е")
    return name in address


class YandexCollector(Collector):
    """Сбор по Яндекс Картам: листание выдачи, пока приходят новые организации."""

    def search_url(self, request: SearchRequest, page: int) -> str:
        text = quote(f"{request.query} {request.city.name}".strip())
        url = f"{SITE}/?text={text}"
        if page > 1:
            url += f"&page={page}"
        return url

    def collect(self, request: SearchRequest) -> Report:
        report = Report()
        found: dict[str, Company] = {}
        skipped = 0
        for page in range(1, MAX_PAGES + 1):
            if len(found) >= request.limit:
                break
            url = self.search_url(request, page)
            try:
                state = parse_state(self.fetcher.get(url))
            except FetchError as exc:
                self.log(f"Яндекс: {exc}")
                break
            report.requests += 1
            report.pages += 1
            items = results_of(state).get("items") or []
            new = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == _ORG_TYPE and not _in_city(item, request.city):
                    skipped += 1
                    continue
                company = company_from(item, request.city)
                if company and company.source_id not in found:
                    found[company.source_id] = company
                    new += 1
            if not new:
                report.capped = page > 1  # выдача кончилась
                break
            if page % 4 == 0:
                self.log(f"Яндекс: страница {page}, собрано {len(found)}")
        if skipped:
            self.log(f"Яндекс: пропущено {skipped} мест из других городов")
        report.exhaustive = len(found) < request.limit
        self.log(f"Яндекс: в выдаче {len(found)} организаций")

        companies = list(found.values())[: request.limit]
        for company in companies:
            self._emit(report, company)
        return report

    def enrich(self, company: Company) -> Company:
        """Карточка организации. Нужна редко: в выдаче и так есть контакты."""
        state = parse_state(self.fetcher.get(company.url))
        items = results_of(state).get("items") or []
        for item in items:
            if isinstance(item, dict) and str(item.get("id")) == company.source_id:
                links = links_from(item)
                return replace(company, links=links or company.links, detailed=True)
        return company


Yandex = Source(
    key=KEY,
    title="Яндекс Карты",
    site=SITE,
    colour="FC3F1D",  # фирменный красный Яндекса
    collector=YandexCollector,
    gives=(PHONE, WEBSITE, VK, TELEGRAM, WHATSAPP, INSTAGRAM, ODNOKLASSNIKI, YOUTUBE, FACEBOOK, TWITTER, VIBER),
    page_size=PAGE_SIZE,
    note="25 мест на странице, контакты сразу в выдаче; почту Яндекс не публикует",
)
