"""ИНН и дата регистрации из открытого ЕГРЮЛ.

На карте у фирмы вывеска, а в реестре — полное наименование: «Кофе Брют» против
«ООО "СЁРФ КОФЕ ТЮМЕНЬ"». Поиск по вывеске находит однофамильцев из других регионов,
и приписать фирме чужой ИНН хуже, чем не приписать никакого. Поэтому совпадение
принимается только строгое: название после снятия формы собственности и кавычек
совпадает целиком, регион регистрации совпадает с регионом города, и такой
кандидат ровно один.

Дата регистрации — отдельная ценность: фирма, открывшаяся месяц назад, ещё ничего
не заказала и ни с кем не работает.

Запрос к реестру стоит двух обращений на фирму, поэтому поиск ИНН включается
отдельно и по умолчанию выключен.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime

from .http import Fetcher, FetchError
from .normalize import name_key

SITE = "https://egrul.nalog.ru"
SEARCH_PAUSE = 1.5  # реестр не любит частых обращений
LEGAL_FORMS = (
    "общество с ограниченной ответственностью",
    "акционерное общество",
    "публичное акционерное общество",
    "непубличное акционерное общество",
    "закрытое акционерное общество",
    "открытое акционерное общество",
    "индивидуальный предприниматель",
    "ооо", "оао", "зао", "пао", "ао", "ип",
)
_QUOTES_RE = re.compile(r"[«»\"'`“”„]+")
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Entity:
    """Запись реестра."""

    inn: str = ""
    ogrn: str = ""
    kpp: str = ""
    name: str = ""  # полное наименование
    short: str = ""  # краткое, как в вывеске
    head: str = ""  # руководитель
    region: str = ""
    registered: date | None = None
    kind: str = ""  # ul — организация, ip — предприниматель

    @property
    def is_person(self) -> bool:
        """Предприниматель — физическое лицо: его данные трогать осторожнее."""
        return self.kind == "ip"

    def age_days(self, today: date | None = None) -> int | None:
        if not self.registered:
            return None
        return ((today or date.today()) - self.registered).days


def clean_name(text: str) -> str:
    """«ООО "СЁРФ КОФЕ ТЮМЕНЬ"» → «серф кофе тюмень»."""
    value = _QUOTES_RE.sub(" ", (text or "").lower().replace("ё", "е"))
    value = _SPACE_RE.sub(" ", value).strip()
    for form in LEGAL_FORMS:
        if value.startswith(form + " "):
            value = value[len(form) :].strip()
            break
    return name_key(value)


def _rows(payload: str) -> list[dict]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    rows = data.get("rows")
    return rows if isinstance(rows, list) else []


def _entity(row: dict) -> Entity:
    registered = None
    raw = str(row.get("r", "")).strip()
    if raw:
        try:
            registered = datetime.strptime(raw, "%d.%m.%Y").date()
        except ValueError:
            registered = None
    short = str(row.get("c", "")).split(";")[0].strip()
    return Entity(
        inn=str(row.get("i", "")).strip(),
        ogrn=str(row.get("o", "")).strip(),
        kpp=str(row.get("p", "")).strip(),
        name=str(row.get("n", "")).strip(),
        short=short,
        head=str(row.get("g", "")).strip(),
        region=str(row.get("rn", "")).strip(),
        registered=registered,
        kind=str(row.get("k", "")).strip(),
    )


def search(query: str, fetcher: Fetcher) -> list[Entity]:
    """Ищет в реестре по названию. Два обращения: получить талон и забрать по нему ответ."""
    if not query.strip():
        return []
    started = fetcher.post(
        f"{SITE}/",
        {"vyp3CaptchaToken": "", "page": "", "query": query, "region": "", "PreventChromeAutocomplete": ""},
    )
    try:
        token = json.loads(started).get("t", "")
    except json.JSONDecodeError:
        return []
    if not token:
        return []
    answer = fetcher.get(f"{SITE}/search-result/{token}", headers={"X-Requested-With": "XMLHttpRequest"})
    return [_entity(row) for row in _rows(answer)]


def pick(name: str, region: str, found: list[Entity]) -> Entity | None:
    """Единственный кандидат, у которого совпали и название, и регион. Иначе — ничего."""
    wanted = clean_name(name)
    if not wanted:
        return None
    region_key = (region or "").lower().replace("ё", "е")
    matched = []
    for entity in found:
        names = {clean_name(entity.short), clean_name(entity.name)}
        if wanted not in names:
            continue
        if region_key and entity.region and region_key.split()[0] not in entity.region.lower().replace("ё", "е"):
            continue
        matched.append(entity)
    # Два однофамильца — значит, непонятно, кто из них; лучше пусто, чем чужой ИНН.
    return matched[0] if len(matched) == 1 else None


def lookup(name: str, city: str, region: str, fetcher: Fetcher) -> Entity | None:
    """Находит фирму в реестре по вывеске и городу."""
    try:
        found = search(f"{name} {city}".strip(), fetcher)
    except FetchError:
        return None
    return pick(name, region, found)
