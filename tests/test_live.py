"""Канарейка: проверка, что карты ещё отдают данные в том же виде.

Все остальные тесты идут по сохранённым страницам и останутся зелёными, даже
если 2ГИС завтра переделает своё состояние, — а программа у пользователя сломается.
Эти тесты ходят в сеть по-настоящему и падают ровно тогда, когда формат изменился.

Поэтому они помечены `live` и в обычный прогон не попадают: их гоняет отдельное
задание раз в неделю.

    pytest -m live
"""

from __future__ import annotations

import pytest

from mapsparser.cities import City
from mapsparser.http import Fetcher
from mapsparser.sources import SearchRequest
from mapsparser.sources.twogis import TwoGisCollector, region_bounds, search_summary
from mapsparser.sources.twogis import parse_state as twogis_state
from mapsparser.sources.yandex import YandexCollector, results_of
from mapsparser.sources.yandex import parse_state as yandex_state

pytestmark = pytest.mark.live

CITY = City(name="Тюмень", alias="tyumen", region="Тюменская область")
QUERY = "кофейня"


@pytest.fixture(scope="module")
def fetcher() -> Fetcher:
    with Fetcher(delay=2.0, retries=2) as ready:
        yield ready


def test_2gis_still_serves_its_state(fetcher: Fetcher) -> None:
    state = twogis_state(fetcher.get(f"https://2gis.ru/{CITY.alias}"))
    assert region_bounds(state), "2ГИС перестал отдавать границы города"


def test_2gis_search_still_has_organisations(fetcher: Fetcher) -> None:
    report = TwoGisCollector(fetcher).collect(
        SearchRequest(query=QUERY, city=CITY, limit=12, deep=False)
    )
    assert report.companies, "2ГИС ничего не отдал по обычному запросу"
    first = report.companies[0]
    assert first.name
    assert first.address or (first.lat and first.lon)


def test_2gis_card_still_has_contacts(fetcher: Fetcher) -> None:
    """Ради этого 2ГИС в сборе и нужен: почты не отдаёт больше никто."""
    report = TwoGisCollector(fetcher).collect(
        SearchRequest(query=QUERY, city=CITY, limit=12, deep=True)
    )
    with_contacts = [company for company in report.companies if company.links]
    assert with_contacts, "ни в одной карточке 2ГИС не нашлось контактов"
    assert any(company.phones for company in with_contacts)


def test_2gis_page_ceiling_is_still_five(fetcher: Fetcher) -> None:
    """Если потолок изменится, сбор плитками станет лишней работой — это надо знать."""
    collector = TwoGisCollector(fetcher)
    request = SearchRequest(query="магазин", city=CITY, limit=12, deep=False)
    sixth = collector.search_url(request, 6, None)
    state = twogis_state(fetcher.get(sixth))
    assert search_summary(state).get("currentPage") == 1, "2ГИС стал отдавать шестую страницу — потолок изменился"


def test_yandex_still_serves_its_state(fetcher: Fetcher) -> None:
    url = YandexCollector(fetcher).search_url(SearchRequest(query=QUERY, city=CITY), 1)
    results = results_of(yandex_state(fetcher.get(url)))
    assert results.get("items"), "Яндекс перестал отдавать выдачу"


def test_yandex_search_still_carries_contacts(fetcher: Fetcher) -> None:
    """У Яндекса контакты лежат прямо в выдаче — на этом держится весь расчёт скорости."""
    report = YandexCollector(fetcher).collect(SearchRequest(query=QUERY, city=CITY, limit=25))
    assert report.companies
    assert any(company.phones for company in report.companies), "в выдаче Яндекса пропали телефоны"
    assert any(company.rating for company in report.companies)


def test_yandex_still_pages(fetcher: Fetcher) -> None:
    collector = YandexCollector(fetcher)
    request = SearchRequest(query=QUERY, city=CITY)
    first = results_of(yandex_state(fetcher.get(collector.search_url(request, 1)))).get("items", [])
    second = results_of(yandex_state(fetcher.get(collector.search_url(request, 2)))).get("items", [])
    ids_first = {item.get("id") for item in first if item.get("type") == "business"}
    ids_second = {item.get("id") for item in second if item.get("type") == "business"}
    assert ids_second - ids_first, "вторая страница Яндекса перестала приносить новые фирмы"
