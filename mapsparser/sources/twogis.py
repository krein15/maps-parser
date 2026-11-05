"""2ГИС: выдача поиска и карточка организации.

Страница собирается на сервере, а её состояние лежит в теле документа присваиванием
`var initialState = JSON.parse('…')`. Внутри одинарных кавычек — обычный JSON,
экранированный по правилам JavaScript: снимаем только этот внешний слой,
всё остальное разберёт `json.loads`.

Что определяет работу сборщика:
 - выдача отдаёт 12 организаций на страницу и листается до конца: с ноября 2026 года
   2ГИС больше не обрывает её на пятой странице;
 - контактов в выдаче нет вообще — почта, сайт и соцсети появляются только в карточке,
   поэтому на каждую организацию нужен отдельный запрос.

Раньше выдача обрывалась на пятой странице: с шестой сервер молча возвращал первую.
Сборщик по-прежнему это замечает и, если потолок вернётся, обходит его плитками карты
(вьюпорт в адресе строго сужает поиск).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import replace
from datetime import datetime
from typing import Any
from urllib.parse import quote

from ..cities import City
from ..display import plural
from ..http import FetchError
from ..models import (
    EMAIL,
    INSTAGRAM,
    ODNOKLASSNIKI,
    PHONE,
    TELEGRAM,
    VIBER,
    VK,
    WEBSITE,
    WHATSAPP,
    YOUTUBE,
    Company,
    Link,
)
from ..normalize import classify_website, clean_title, email, phone, social_kind, strip_city
from .base import Collector, Report, SearchRequest, Source

KEY = "2gis"
SITE = "https://2gis.ru"
PAGE_SIZE = 12
# Каждая плитка листается до потолка заново, так что плиток нужно с запасом: участки
# неравны, и в центре города организаций больше, чем на окраине.
_TILE_SPARE = 1.8
_BROKEN = -1  # выдача не долистана из-за сетевой ошибки
# Страница без новых организаций ещё не конец: в глубине выдачи попадаются страницы из одних
# домов и улиц. Конец — когда так идёт несколько страниц подряд.
_EMPTY_PAGES_IN_A_ROW = 3

_STATE_RE = re.compile(r"var\s+initialState\s*=\s*JSON\.parse\('(.*?)'\);", re.S)
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
_JS_ESCAPE_RE = re.compile(r"\\(.)", re.S)
_POLYGON_RE = re.compile(r"(-?\d+\.?\d*)\s+(-?\d+\.?\d*)")

DAYS = (("Mon", "Пн"), ("Tue", "Вт"), ("Wed", "Ср"), ("Thu", "Чт"), ("Fri", "Пт"), ("Sat", "Сб"), ("Sun", "Вс"))
ORGANIZATION_TYPES = ("branch", "filial", "organization")

# Ширина окна карты в градусах долготы: 360° / 2^zoom, умноженные на отношение окна к тайлу
# (примерно 1000 px к 256 px). Проверено на плитках Тюмени.
_VIEWPORT_TILES = 3.9


def unescape_js(text: str) -> str:
    """Снимает экранирование JavaScript, не трогая экранирование внутри самого JSON."""
    return _JS_ESCAPE_RE.sub(lambda m: _ESCAPES.get(m.group(1), m.group(1)), text)


def parse_state(html: str) -> dict[str, Any]:
    """Состояние страницы 2ГИС."""
    match = _STATE_RE.search(html)
    if not match:
        raise FetchError("2ГИС: состояние страницы не найдено — похоже, формат сайта изменился")
    try:
        return json.loads(unescape_js(match.group(1)))
    except json.JSONDecodeError as exc:
        raise FetchError(f"2ГИС: состояние страницы не разобрать ({exc})") from exc


def entities(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Карточки объектов со страницы: «идентификатор → данные»."""
    profile = state.get("data", {}).get("entity", {}).get("profile", {}) or {}
    return {key: node["data"] for key, node in profile.items() if isinstance(node, dict) and node.get("data")}


def search_summary(state: dict[str, Any]) -> dict[str, Any]:
    """Сводка выдачи: сколько всего нашлось и какая страница показана."""
    profile = state.get("data", {}).get("search", {}).get("profile", {}) or {}
    for node in profile.values():
        data = node.get("data") if isinstance(node, dict) else None
        if isinstance(data, dict) and "total" in data:
            return data
    return {}


def region_bounds(state: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Границы города: (min_lon, min_lat, max_lon, max_lat) из POLYGON в описании региона."""
    profile = state.get("data", {}).get("region", {}).get("profile", {}) or {}
    for node in profile.values():
        data = node.get("data") if isinstance(node, dict) else None
        polygon = (data or {}).get("bounds")
        if not polygon:
            continue
        points = [(float(lon), float(lat)) for lon, lat in _POLYGON_RE.findall(polygon)]
        if points:
            lons = [p[0] for p in points]
            lats = [p[1] for p in points]
            return (min(lons), min(lats), max(lons), max(lats))
    return None


def region_info(state: dict[str, Any]) -> tuple[str, str]:
    """Название города по версии 2ГИС и идентификатор его региона."""
    profile = state.get("data", {}).get("region", {}).get("profile", {}) or {}
    for key, node in profile.items():
        data = node.get("data") if isinstance(node, dict) else None
        if isinstance(data, dict):
            return str(data.get("name", "")), str(data.get("id", key))
    return "", ""


def schedule_text(schedule: Any) -> str:
    """Режим работы из словаря дней в строку «Пн–Пт 09:00–22:00, Сб 10:00–18:00»."""
    if not isinstance(schedule, dict):
        return ""
    if schedule.get("is_24x7"):
        return "круглосуточно"
    parts: list[tuple[str, str]] = []
    for key, title in DAYS:
        day = schedule.get(key)
        if not isinstance(day, dict):
            continue
        hours = day.get("working_hours") or []
        text = ", ".join(f"{h.get('from', '')}–{h.get('to', '')}" for h in hours if isinstance(h, dict))
        if text:
            parts.append((title, text))
    if not parts:
        return ""
    # Склеиваем соседние дни с одинаковым временем: «Пн–Пт 09:00–22:00».
    chunks: list[str] = []
    start, hours = parts[0]
    previous = start
    for title, text in parts[1:]:
        if text == hours:
            previous = title
            continue
        chunks.append(f"{start}–{previous} {hours}" if start != previous else f"{start} {hours}")
        start, previous, hours = title, title, text
    chunks.append(f"{start}–{previous} {hours}" if start != previous else f"{start} {hours}")
    return ", ".join(chunks)


def links_from_contacts(groups: Any) -> tuple[Link, ...]:
    """Контакты карточки 2ГИС в общем виде."""
    links: list[Link] = []
    for group in groups or []:
        for contact in (group or {}).get("contacts", []):
            if not isinstance(contact, dict):
                continue
            kind = contact.get("type", "")
            raw = contact.get("url") or contact.get("value") or contact.get("text") or ""
            title = clean_title(contact.get("text", "")) or raw
            if kind == "phone":
                value = phone(contact.get("value") or contact.get("text", ""))
                if value:
                    links.append(Link(PHONE, value, title))
            elif kind == "email":
                value = email(contact.get("value") or contact.get("text", ""))
                if value:
                    links.append(Link(EMAIL, value, value))
            elif kind == "website":
                # В value спрятан счётчик переходов link.2gis.ru, в text — настоящий адрес.
                # Под видом сайта часто лежит ссылка на телеграм или ВК — разбираем по хосту.
                found, value = classify_website(contact.get("text", ""))
                if not value:
                    found, value = classify_website(raw)
                if value:
                    links.append(Link(found, value, value))
            elif kind in ("fax", "office_phone", "icq", "skype"):
                continue
            elif str(raw).startswith("http"):
                value = str(raw).split("?", 1)[0].strip()
                links.append(Link(social_kind(value), value, title))
    return tuple(links)


def address_of(data: dict[str, Any]) -> str:
    """Адрес строкой: «Профсоюзная улица, 56»."""
    name = clean_title(data.get("address_name", ""))
    if name:
        return name
    for component in (data.get("address") or {}).get("components") or []:
        street = component.get("street", "")
        if street:
            return clean_title(f"{street}, {component.get('number', '')}".strip().rstrip(", "))
    return clean_title(data.get("address_comment", ""))


def company_from(data: dict[str, Any], key: str, city: City) -> Company | None:
    """Организация из данных 2ГИС. None — если это не организация (дом, улица, остановка)."""
    if data.get("type") not in ORGANIZATION_TYPES:
        return None
    name = clean_title((data.get("name_ex") or {}).get("primary") or data.get("name", ""))
    if not name:
        return None
    point = data.get("point") or {}
    reviews = data.get("reviews") or {}
    rating = reviews.get("general_rating") or reviews.get("org_rating")
    count = reviews.get("general_review_count_with_stars") or reviews.get("general_review_count")
    identifier = str(data.get("id") or key).split("_")[0]
    alias = data.get("city_alias") or city.alias
    return Company(
        source=KEY,
        source_id=identifier,
        name=name,
        url=f"{SITE}/{alias}/firm/{identifier}",
        address=strip_city(address_of(data), city.name),
        city=city.name,
        lat=point.get("lat"),
        lon=point.get("lon"),
        rubrics=tuple(
            clean_title(r.get("name", ""))
            for r in (data.get("rubrics") or [])
            if isinstance(r, dict) and r.get("name")
        ),
        rating=float(rating) if rating else None,
        reviews=int(count) if count else None,
        links=links_from_contacts(data.get("contact_groups")),
        schedule=schedule_text(data.get("schedule")),
        branch_count=(data.get("org") or {}).get("branch_count"),
        verified_owner=None,  # 2ГИС этого не показывает
        is_advert=bool(data.get("is_promoted")),
        detailed="contact_groups" in data,
        collected_at=datetime.now().astimezone(),
    )


def zoom_for(span_lon: float) -> int:
    """Зум, при котором окно карты примерно равно ширине плитки."""
    zoom = math.log2(360 * _VIEWPORT_TILES / max(span_lon, 0.0005))
    return max(10, min(17, round(zoom)))


def tiles_for(bounds: tuple[float, float, float, float], count: int) -> list[tuple[float, float, int]]:
    """Режет город на плитки: список (долгота, широта, зум) для центра каждой."""
    min_lon, min_lat, max_lon, max_lat = bounds
    width = max(max_lon - min_lon, 0.01)
    height = max(max_lat - min_lat, 0.01)
    if count <= 1:
        return [((min_lon + max_lon) / 2, (min_lat + max_lat) / 2, zoom_for(width))]
    # Сетка по форме города: вытянутый город режем сильнее вдоль длинной стороны.
    ratio = width / max(height, 0.001)
    columns = max(1, round(math.sqrt(count * ratio)))
    rows = max(1, math.ceil(count / columns))
    step_lon = width / columns
    step_lat = height / rows
    zoom = zoom_for(step_lon)
    return [
        (min_lon + step_lon * (column + 0.5), min_lat + step_lat * (row + 0.5), zoom)
        for row in range(rows)
        for column in range(columns)
    ]


class TwoGisCollector(Collector):
    """Сбор по 2ГИС: выдача по всему городу, плитки — только если она оборвалась, потом карточки."""

    def search_url(self, request: SearchRequest, page: int, tile: tuple[float, float, int] | None) -> str:
        url = f"{SITE}/{request.city.alias}/search/{quote(request.query)}"
        if page > 1:
            url += f"/page/{page}"
        if tile:
            lon, lat, zoom = tile
            url += f"?m={lon:.6f}%2C{lat:.6f}%2F{zoom}"
        return url

    def city_bounds(self, city: City) -> tuple[float, float, float, float] | None:
        state = parse_state(self.fetcher.get(f"{SITE}/{city.alias}"))
        return region_bounds(state)

    def collect(self, request: SearchRequest) -> Report:
        report = Report()
        found: dict[str, Company] = {}
        ceiling = self._collect_tile(request, None, found, report)
        covered = ceiling is None
        if ceiling and ceiling > 0 and len(found) < request.limit:
            covered = self._collect_tiles(request, ceiling, found, report)
        # «Показал всё» — только если выдача кончилась сама, а не оборвалась на потолке.
        report.exhaustive = covered and len(found) < request.limit
        self.log(f"2ГИС: в выдаче {len(found)} организаций")

        companies = list(self.fresh(found).values())[: request.limit]
        if request.deep and companies:
            companies = self._enrich_all(companies, report)
        for company in companies:
            self._emit(report, company)
        report.cards = sum(1 for c in companies if c.detailed)
        return report

    def _collect_tiles(self, request: SearchRequest, ceiling: int, found: dict[str, Company], report: Report) -> bool:
        """Запасной путь на случай, если 2ГИС снова обрывает выдачу: режет город на участки.

        Возвращает True, только если каждый участок долистан до конца — тогда город показан целиком.
        """
        per_query = PAGE_SIZE * ceiling
        wanted = request.tiles or math.ceil(request.limit / per_query * _TILE_SPARE)
        bounds = self.city_bounds(request.city)
        report.requests += 1
        if not bounds:
            self.log(f"2ГИС: границы города не нашлись — соберу только первые {per_query} мест")
            return False
        grid = tiles_for(bounds, min(wanted, 100))
        spots = plural(len(grid), "участок", "участка", "участков")
        self.log(f"2ГИС: выдача обрывается на {per_query} местах, поэтому режу город на {spots}")
        whole = True
        for tile in grid:
            if len(found) >= request.limit:
                break
            if self._collect_tile(request, tile, found, report) is not None:
                whole = False  # участок тоже упёрся в потолок или не открылся
        return whole

    def _collect_tile(
        self,
        request: SearchRequest,
        tile: tuple[float, float, int] | None,
        found: dict[str, Company],
        report: Report,
    ) -> int | None:
        """Листает выдачу до конца.

        None — выдача кончилась или набрано сколько нужно; число страниц — выдача оборвалась
        на потолке; `_BROKEN` — не долистали из-за сетевой ошибки.
        """
        page = 0
        empty = 0
        while len(found) < request.limit:
            page += 1
            url = self.search_url(request, page, tile)
            try:
                state = parse_state(self.fetcher.get(url))
            except FetchError as exc:
                self.log(f"2ГИС: {exc}")
                return _BROKEN
            report.requests += 1
            report.pages += 1
            summary = search_summary(state)
            if page > 1 and summary.get("currentPage") != page:
                # Сервер вместо следующей страницы вернул первую: это потолок, а не конец выдачи.
                report.capped = True
                return page - 1
            if page == 1 and tile is None and summary.get("total"):
                self.log(f"2ГИС: по запросу «{request.query}» в выдаче {summary['total']} мест")
            new = 0
            for key, data in entities(state).items():
                company = company_from(data, key, request.city)
                if company and company.source_id not in found:
                    found[company.source_id] = company
                    new += 1
            empty = 0 if new else empty + 1
            if empty >= _EMPTY_PAGES_IN_A_ROW or summary.get("pages", 0) <= page:
                return None
            if page % 25 == 0:
                self.log(f"2ГИС: пролистано {page} из {summary.get('pages')} страниц")
        return None

    def _enrich_all(self, companies: list[Company], report: Report) -> list[Company]:
        """Открывает карточку каждой организации: только там есть почта, сайт и соцсети."""
        total = len(companies)
        self.log(f"2ГИС: открываю карточки ради контактов — {total} шт.")
        result: list[Company] = []
        for number, company in enumerate(companies, 1):
            try:
                result.append(self.enrich(company))
                report.requests += 1
            except FetchError as exc:
                self.log(f"2ГИС: карточка «{company.name}» не открылась ({exc})")
                result.append(company)
            if number % 25 == 0 or number == total:
                self.log(f"2ГИС: карточек открыто {number} из {total}")
        return result

    def enrich(self, company: Company) -> Company:
        """Добирает контакты из карточки организации."""
        state = parse_state(self.fetcher.get(company.url))
        for key, data in entities(state).items():
            if str(data.get("id", key)).split("_")[0] != company.source_id:
                continue
            links = links_from_contacts(data.get("contact_groups"))
            return replace(
                company,
                links=links,
                schedule=schedule_text(data.get("schedule")) or company.schedule,
                detailed=True,
            )
        return company


TwoGis = Source(
    key=KEY,
    title="2ГИС",
    site=SITE,
    colour="00A651",  # фирменный зелёный 2ГИС
    collector=TwoGisCollector,
    gives=(PHONE, EMAIL, WEBSITE, VK, TELEGRAM, WHATSAPP, INSTAGRAM, ODNOKLASSNIKI, YOUTUBE, VIBER),
    page_size=PAGE_SIZE,
    needs_city_alias=True,  # без короткого имени города 2ГИС отвечает 404
    note="12 мест на странице, выдача листается до конца; контакты — только в карточке",
)
