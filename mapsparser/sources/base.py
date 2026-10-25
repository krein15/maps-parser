"""Договор источника.

Карта описывается одним объектом `Source`: ключ, название, цвет в отчёте, сборщик и —
главное — что эта карта в принципе умеет отдавать. Последнее не украшение: колонка
«чего у фирмы нет» имеет смысл, только если известно, что источник вообще показывает
почту. Яндекс её не публикует никогда, поэтому «нет почты» можно писать лишь тогда,
когда в сборе участвовал 2ГИС.

Ядро не знает ни одного ключа источника по имени: окно, флаги командной строки,
колонки отчёта и пробелы собираются из этого описания. Новая карта — это новый
`Source`, а не правки по всему коду.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from ..cities import City
from ..http import Fetcher
from ..models import Company


@dataclass(frozen=True)
class SearchRequest:
    """Что именно собирать."""

    query: str  # «кофейня», «автосервис»
    city: City
    limit: int = 300  # сколько организаций нужно
    deep: bool = True  # открывать карточку ради контактов, если в выдаче их нет
    tiles: int = 0  # на сколько плиток резать город; 0 — выбрать самому


@dataclass
class Report:
    """Что получилось у источника: сами организации и честный счёт запросов."""

    companies: list[Company] = field(default_factory=list)
    requests: int = 0
    pages: int = 0
    cards: int = 0
    capped: bool = False  # упёрлись в потолок источника, а не в запрос пользователя
    exhaustive: bool = False  # источник показал всё, что у него есть по этому запросу
    note: str = ""


class Collector:
    """Сборщик одной карты. Наследники переопределяют `collect`."""

    source: Source  # проставляется при описании источника

    def __init__(
        self,
        fetcher: Fetcher,
        *,
        log: Callable[[str], None] | None = None,
        on_company: Callable[[Company], None] | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.log = log or (lambda _message: None)
        self.on_company = on_company or (lambda _company: None)

    def collect(self, request: SearchRequest) -> Report:
        raise NotImplementedError

    def enrich(self, company: Company) -> Company:
        """Добирает контакты из карточки. По умолчанию добирать нечего."""
        return company

    # Мелкая помощь наследникам
    def _emit(self, report: Report, company: Company) -> None:
        report.companies.append(company)
        self.on_company(company)


@dataclass(frozen=True)
class Source:
    """Описание карты для ядра программы."""

    key: str  # «2gis», «yandex» — им же помечаются колонки и флаги
    title: str  # «2ГИС»
    site: str  # адрес карты, для ссылок в отчёте
    colour: str  # цвет заголовка колонки в Excel, без решётки
    collector: type[Collector]
    gives: tuple[str, ...]  # виды контактов, которые карта вообще показывает
    page_size: int  # сколько организаций на странице выдачи
    needs_city_alias: bool = False  # карте нужен её собственный адрес города
    note: str = ""  # что полезно знать про потолки источника

    def __post_init__(self) -> None:
        # Сборщик должен знать своё описание: так он не повторяет ключ источника у себя внутри.
        self.collector.source = self

    def can_give(self, kind: str) -> bool:
        return kind in self.gives

    def make(
        self,
        fetcher: Fetcher,
        *,
        log: Callable[[str], None] | None = None,
        on_company: Callable[[Company], None] | None = None,
    ) -> Collector:
        return self.collector(fetcher, log=log, on_company=on_company)


def paged(limit: int, page_size: int) -> Iterator[int]:
    """Номера страниц, которых хватит на `limit` организаций, начиная с первой."""
    page = 1
    while (page - 1) * page_size < limit:
        yield page
        page += 1
