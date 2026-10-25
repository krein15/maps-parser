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
from .cache import Cache
from .cities import City
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
    check_sites: bool = True  # заходить на сайты фирм за почтами и состоянием сайта
    site_limit: int = 400  # сколько сайтов проверять за один сбор


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

    with Fetcher(delay=settings.delay, cache=cache, log=say, stop=stop) as fetcher:
        for source in settings.sources:
            if stop and stop():
                # Кнопку «Остановить» нажали между картами: ко второй уже не идём.
                result.stopped = True
                say("Остановлено. Сохраняю то, что успели собрать.")
                break
            say(f"— {source.title}: ищу «{settings.query}» в городе {settings.city.name}")
            collector = source.make(fetcher, log=say)
            request = SearchRequest(
                query=settings.query,
                city=settings.city,
                limit=settings.limit,
                deep=settings.deep,
                tiles=settings.tiles,
            )
            try:
                report = collector.collect(request)
            except Stopped:
                result.stopped = True
                say("Остановлено. Сохраняю то, что успели собрать.")
                break
            result.reports[source.key] = report
            companies.extend(report.companies)
            if report.capped:
                say(f"— {source.title}: источник отдал всё, что показывает по этому запросу")

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

    context = gaps_module.Context(
        sources=tuple(settings.sources),
        exhaustive=frozenset(key for key, report in result.reports.items() if report.exhaustive),
        sites_checked=bool(checked),
    )
    places = gaps_module.apply(places, context)
    places = [place for place in places if _wanted(place, settings, context)]
    result.places = places
    result.context = context
    result.finished_at = datetime.now().astimezone()
    if on_place:
        for place in places:
            on_place(place)
    say(
        f"Готово: {len(places)} фирм, из них в обеих картах {result.in_both}. "
        f"Запросов к картам {result.requests}, времени {result.seconds:.0f} с."
    )
    return result


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


def _wanted(place: Place, settings: Settings, context: gaps_module.Context) -> bool:
    if place.score < settings.min_score:
        return False
    if settings.required_gaps:
        codes = set(gaps_module.codes_for(place, context))
        if not set(settings.required_gaps) <= codes:
            return False
    return True
