"""Весь путь сбора: карты → организации → сведение → пробелы → отчёт.

Один вызов `run` делает то же самое, что кнопка «Найти» в окне и команда `collect`
в командной строке, — чтобы окно и консоль не разъезжались в поведении.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import gaps as gaps_module
from . import niches as niches_module
from .cache import Cache
from .cities import City
from .display import plural
from .egrul import SEARCH_PAUSE as EGRUL_PAUSE
from .egrul import lookup
from .history import Changes, History, compare, run_key
from .history import summary as history_summary
from .http import Fetcher, Stopped
from .merge import merge
from .models import EMAIL, PHONE, Company, Link, Place
from .settings import default_cache_dir
from .sources import Report, SearchRequest, Source, all_sources
from .website import check as check_site


@dataclass
class Settings:
    """Что собирать и как себя вести."""

    query: str
    city: City
    sources: list[Source] = field(default_factory=all_sources)
    limit: int = 300
    deep: bool = True  # открывать карточки 2ГИС ради почты
    delay: float = 1.5
    use_cache: bool = True
    cache_hours: float = 24.0
    cache_dir: Path | None = None
    tiles: int = 0
    min_score: int = 0
    required_gaps: tuple[str, ...] = ()  # коды пробелов, без которых фирма не нужна
    skip_chains: bool = False  # выкинуть сетевые точки: решение принимает не филиал
    check_sites: bool = True  # заходить на сайты фирм за почтами и состоянием сайта
    remember: bool = True  # помнить сбор, чтобы в следующий раз показать изменения
    history_dir: Path | None = None
    queries: tuple[str, ...] = ()  # если пусто — берутся из ниши или из самого запроса
    site_limit: int = 400  # сколько сайтов проверять за один сбор
    find_inn: bool = False  # искать ИНН в ЕГРЮЛ: два обращения к реестру на фирму
    inn_limit: int = 100

    def all_queries(self) -> tuple[str, ...]:
        """Запросы сбора: заданные прямо, иначе набор ниши, иначе само слово."""
        if self.queries:
            return self.queries
        return niches_module.queries_for(self.query)


@dataclass
class Result:
    """Что получилось."""

    settings: Settings
    places: list[Place] = field(default_factory=list)
    reports: dict[str, Report] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stopped: bool = False
    sites_checked: int = 0
    inn_found: int = 0
    changes: Changes = field(default_factory=Changes)
    context: gaps_module.Context = field(default_factory=gaps_module.Context)

    @property
    def requests(self) -> int:
        return sum(report.requests for report in self.reports.values())

    @property
    def collected(self) -> int:
        return sum(len(report.companies) for report in self.reports.values())

    @property
    def seconds(self) -> float:
        if not self.started_at or not self.finished_at:
            return 0.0
        return (self.finished_at - self.started_at).total_seconds()

    def count_in(self, source_key: str) -> int:
        return sum(1 for place in self.places if source_key in place.by_source)

    @property
    def in_both(self) -> int:
        return sum(1 for place in self.places if len(place.by_source) > 1)


def run(
    settings: Settings,
    *,
    log: Callable[[str], None] | None = None,
    on_place: Callable[[Place], None] | None = None,
    stop: Callable[[], bool] | None = None,
) -> Result:
    """Собирает организации по всем выбранным картам и сводит их в список фирм."""
    say = log or (lambda _message: None)
    result = Result(settings=settings, started_at=datetime.now().astimezone())
    cache = Cache(settings.cache_dir or default_cache_dir(), settings.cache_hours) if settings.use_cache else None
    companies: list[Company] = []

    queries = settings.all_queries()
    if len(queries) > 1:
        asked = plural(len(queries), "запрос", "запроса", "запросов")
        say(f"Ниша «{settings.query}» — это {asked}: {', '.join(queries)}")
    per_query = niches_module.share(settings.limit, len(queries))

    with Fetcher(delay=settings.delay, cache=cache, log=say, stop=stop) as fetcher:
        for source in settings.sources:
            if source.needs_city_alias and not settings.city.alias:
                # Город не из справочника: Яндекс найдёт его по названию, 2ГИС — нет.
                say(f"— {source.title} этот город не знает, пропускаю его")
                continue
            if stop and stop():
                # Кнопку «Остановить» нажали между картами: ко второй уже не идём.
                result.stopped = True
                say("Остановлено. Сохраняю то, что успели собрать.")
                break
            collector = source.make(fetcher, log=say)
            total = Report()
            seen: set[str] = set()
            for query in queries:
                if stop and stop():
                    result.stopped = True
                    break
                say(f"— {source.title}: ищу «{query}» в городе {settings.city.name}")
                request = SearchRequest(
                    query=query,
                    city=settings.city,
                    limit=per_query,
                    deep=settings.deep,
                    tiles=settings.tiles,
                )
                try:
                    report = collector.collect(request)
                except Stopped:
                    result.stopped = True
                    say("Остановлено. Сохраняю то, что успели собрать.")
                    break
                _absorb(total, report, seen)
                if report.capped:
                    say(f"— {source.title}: источник отдал всё, что показывает по запросу «{query}»")
            result.reports[source.key] = total
            companies.extend(total.companies)
            if result.stopped:
                break

    say(f"Сводим {len(companies)} карточек в фирмы…")
    places = merge(companies)
    checked = 0
    if settings.check_sites and not result.stopped:
        with Fetcher(delay=settings.delay / 3, retries=1, cache=cache, log=say, stop=stop) as fetcher:
            try:
                checked = _check_sites(places, settings, fetcher, say)
            except Stopped:
                result.stopped = True
                say("Остановлено на проверке сайтов. Сохраняю собранное.")
        result.sites_checked = checked

    if settings.find_inn and not result.stopped:
        with Fetcher(delay=EGRUL_PAUSE, retries=1, cache=cache, log=say, stop=stop) as fetcher:
            try:
                result.inn_found = _find_inn(places, settings, fetcher, say)
            except Stopped:
                result.stopped = True
                say("Остановлено на поиске ИНН. Сохраняю собранное.")

    context = gaps_module.Context(
        sources=tuple(settings.sources),
        exhaustive=frozenset(key for key, report in result.reports.items() if report.exhaustive),
        sites_checked=bool(checked),
    )
    places = gaps_module.apply(places, context)
    places = [place for place in places if _wanted(place, settings, context)]
    result.places = places
    result.context = context

    if settings.remember and not result.stopped:
        # Прерванный сбор в историю не кладём: в нём «пропавшие» фирмы — это те,
        # до которых не дошли руки, и следующий разбор изменений был бы враньём.
        history = History(
            run_key(settings.city.alias or settings.city.name, settings.query),
            settings.history_dir,
        )
        previous, previous_at = history.load()
        result.changes = compare(places, previous, previous_at)
        history.save(places, previous=previous)
        if not result.changes.first_run:
            say(history_summary(result.changes))

    result.finished_at = datetime.now().astimezone()
    if on_place:
        for place in places:
            on_place(place)
    say(
        f"Готово: {len(places)} фирм, из них в обеих картах {result.in_both}. "
        f"Запросов к картам {result.requests}, времени {result.seconds:.0f} с."
    )
    return result


def _absorb(total: Report, report: Report, seen: set[str]) -> None:
    """Складывает отчёт одного запроса в общий, выбрасывая уже виденные организации."""
    for company in report.companies:
        if company.source_id not in seen:
            seen.add(company.source_id)
            total.companies.append(company)
    total.requests += report.requests
    total.pages += report.pages
    total.cards += report.cards
    total.capped = total.capped or report.capped
    # Источник показал всё только если это верно для каждого запроса ниши.
    total.exhaustive = report.exhaustive if total.pages == report.pages else (total.exhaustive and report.exhaustive)


def _check_sites(
    places: list[Place],
    settings: Settings,
    fetcher: Fetcher,
    say: Callable[[str], None],
) -> int:
    """Заходит на сайты фирм: добирает почты и выясняет, работает ли сайт вообще."""
    with_site = [place for place in places if place.websites][: settings.site_limit]
    if not with_site:
        return 0
    say(f"Захожу на сайты фирм ({len(with_site)}) — там обычно лежит почта")
    found_emails = 0
    dead = 0
    for number, place in enumerate(with_site, 1):
        report = check_site(place.websites[0], fetcher)
        place.site = report
        extra: list[Link] = []
        known_emails = set(place.emails)
        for value in report.emails:
            if value not in known_emails:
                extra.append(Link(EMAIL, value, value))
                found_emails += 1
        known_phones = set(place.phones)
        extra.extend(Link(PHONE, value, value) for value in report.phones if value not in known_phones)
        place.extra = tuple(extra)
        if not report.alive:
            dead += 1
        if number % 25 == 0 or number == len(with_site):
            say(f"Сайтов проверено {number} из {len(with_site)}")
    say(f"На сайтах нашлось новых почт: {found_emails}; не открылось сайтов: {dead}")
    return len(with_site)


def _find_inn(
    places: list[Place],
    settings: Settings,
    fetcher: Fetcher,
    say: Callable[[str], None],
) -> int:
    """Ищет фирмы в ЕГРЮЛ. Молчит там, где не уверен: чужой ИНН хуже пустой клетки."""
    wanted = places[: settings.inn_limit]
    say(f"Ищу ИНН в ЕГРЮЛ ({len(wanted)} фирм) — реестр отвечает небыстро")
    found = 0
    for number, place in enumerate(wanted, 1):
        entity = lookup(place.name, settings.city.name, settings.city.region, fetcher)
        if entity:
            place.entity = entity
            found += 1
        if number % 20 == 0 or number == len(wanted):
            say(f"ИНН: проверено {number} из {len(wanted)}, нашлось {found}")
    return found


def _wanted(place: Place, settings: Settings, context: gaps_module.Context) -> bool:
    if place.score < settings.min_score:
        return False
    if settings.skip_chains and place.is_chain:
        return False
    if settings.required_gaps:
        codes = set(gaps_module.codes_for(place, context))
        if not set(settings.required_gaps) <= codes:
            return False
    return True
