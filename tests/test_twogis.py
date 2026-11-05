"""Разбор страниц 2ГИС и то, как сборщик листает выдачу."""

from __future__ import annotations

import json
import re
import zlib

import pytest
from conftest import FakeFetcher, fixture

from mapsparser.http import FetchError
from mapsparser.models import EMAIL, PHONE, TELEGRAM, VK, WEBSITE, WHATSAPP
from mapsparser.sources import SearchRequest, TwoGis
from mapsparser.sources.twogis import (
    PAGE_SIZE,
    TwoGisCollector,
    company_from,
    entities,
    parse_state,
    region_bounds,
    schedule_text,
    search_summary,
    tiles_for,
    unescape_js,
    zoom_for,
)


def test_unescape_js_touches_only_the_outer_layer() -> None:
    """Внутри одинарных кавычек экранированы кавычка и косая — экранирование JSON трогать нельзя."""
    assert unescape_js(r"\'") == "'"
    assert unescape_js(r"\\") == "\\"
    # Внутри JSON «с» — это буква «с»; на внешнем слое она записана двумя косыми,
    # и снять нужно ровно одну, чтобы json.loads увидел обычное экранирование.
    assert json.loads(unescape_js(r'{"a":"\\u0441"}'))["a"] == "с"


def test_parse_state_complains_when_the_format_changes() -> None:
    with pytest.raises(FetchError, match="формат сайта"):
        parse_state("<html><body>ничего похожего</body></html>")


def test_search_page_gives_the_summary_and_the_bounds() -> None:
    state = parse_state(fixture("2gis_search.html"))
    assert search_summary(state)["total"] == 241
    assert search_summary(state)["currentPage"] == 1
    assert region_bounds(state) == (65.40, 57.08, 65.70, 57.22)


def test_only_organisations_become_companies(tyumen) -> None:
    state = parse_state(fixture("2gis_search.html"))
    companies = [company_from(data, key, tyumen) for key, data in entities(state).items()]
    found = [c for c in companies if c]
    assert len(found) == 3  # дом в выдаче пропущен
    assert None in companies
    first = next(c for c in found if c.name == "Ола Ола")
    assert first.address == "Профсоюзная улица, 56"
    assert first.rating == 4.8
    assert first.reviews == 125
    assert first.rubrics == ("Кофейни",)
    assert first.url.endswith("/tyumen/firm/70000001000000001")
    assert first.links == ()  # контактов в выдаче нет


def test_advertising_is_marked(tyumen) -> None:
    state = parse_state(fixture("2gis_search.html"))
    raf = next(
        company_from(data, key, tyumen)
        for key, data in entities(state).items()
        if data.get("name_ex", {}).get("primary") == "Раф"
    )
    assert raf.is_advert is True


def test_card_gives_the_contacts(tyumen) -> None:
    state = parse_state(fixture("2gis_firm.html"))
    key, data = next(iter(entities(state).items()))
    company = company_from(data, key, tyumen)
    assert company.phones == ("+73452666707",)
    assert company.emails == ("ola.ola@mail.ru",)
    assert company.websites == ("http://ola-ola.ru",)  # счётчик переходов развёрнут
    kinds = {link.kind for link in company.links}
    assert kinds == {PHONE, EMAIL, WEBSITE, VK, WHATSAPP, TELEGRAM}  # факс отброшен
    telegram = next(link for link in company.links if link.kind == TELEGRAM)
    assert telegram.value == "https://t.me/olaola"  # лежал в поле «сайт»
    whatsapp = next(link for link in company.links if link.kind == WHATSAPP)
    assert "?text=" not in whatsapp.value
    assert company.detailed is True


def test_schedule_joins_equal_days() -> None:
    state = parse_state(fixture("2gis_firm.html"))
    data = next(iter(entities(state).values()))
    assert schedule_text(data["schedule"]) == "Пн–Пт 09:00–22:00, Сб–Вс 10:00–18:00"
    assert schedule_text({"is_24x7": True}) == "круглосуточно"
    assert schedule_text(None) == ""


def test_tiles_cover_the_city_and_do_not_repeat() -> None:
    bounds = (65.40, 57.08, 65.70, 57.22)
    tiles = tiles_for(bounds, 9)
    assert len(tiles) >= 9
    for lon, lat, zoom in tiles:
        assert bounds[0] <= lon <= bounds[2]
        assert bounds[1] <= lat <= bounds[3]
        assert 10 <= zoom <= 17
    assert len({(lon, lat) for lon, lat, _ in tiles}) == len(tiles)


def test_tiles_of_a_whole_city_are_one_wide_view() -> None:
    assert len(tiles_for((65.40, 57.08, 65.70, 57.22), 1)) == 1


def test_zoom_grows_as_the_tile_shrinks() -> None:
    assert zoom_for(0.3) < zoom_for(0.02)


class PagedSearch(FakeFetcher):
    """Выдача 2ГИС на много страниц: у каждой свой номер и свои организации.

    Сохранённая страница одна, поэтому номер страницы и идентификаторы фирм подставляются
    в неё на лету. `ceiling` повторяет старое поведение 2ГИС: после него сервер молча
    отдаёт первую страницу. `repeat` — страницы, на которых нет ни одной новой фирмы,
    `broken` — страницы, которые не открылись.
    """

    def __init__(
        self,
        pages: int,
        *,
        ceiling: int | None = None,
        repeat: frozenset[int] = frozenset(),
        broken: frozenset[int] = frozenset(),
    ) -> None:
        super().__init__({"/firm/": fixture("2gis_firm.html"), "2gis.ru/tyumen": fixture("2gis_search.html")})
        self.total_pages = pages
        self.ceiling = ceiling
        self.repeat = repeat
        self.broken = broken

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> str:
        if "/search/" not in url:
            return super().get(url, headers=headers)
        self.asked.append(url)
        self.requests_made += 1
        number = re.search(r"/page/(\d+)", url)
        page = int(number.group(1)) if number else 1
        if page in self.broken:
            raise FetchError("сервер ответил 502")
        if self.ceiling and page > self.ceiling:
            page = 1
        tile = re.search(r"\?m=([^%]+)", url)
        own = 1 if page in self.repeat else page  # «повтор» — фирмы уже виденной первой страницы
        prefix = f"7{zlib.crc32(tile.group(1).encode()) % 1000 if tile else 0:03d}{own:04d}"
        text = fixture("2gis_search.html").replace("70000001000000", prefix + "000000")
        text = text.replace('"currentPage": 1', f'"currentPage": {page}')
        return text.replace('"pages": 21', f'"pages": {self.total_pages}')


TYUMEN_STATE = parse_state(fixture("2gis_search.html"))


def search_pages(fetcher: FakeFetcher) -> list[str]:
    return [url for url in fetcher.asked if "/search/" in url]


def test_collector_reads_the_whole_list_without_tiles(tyumen) -> None:
    """Пять страниц больше не потолок: выдача листается до конца, город на участки не режется."""
    fetcher = PagedSearch(pages=8)
    report = TwoGisCollector(fetcher).collect(SearchRequest(query="магазин", city=tyumen, limit=600, deep=False))
    assert len(report.companies) == 8 * 3
    assert len(search_pages(fetcher)) == 8
    assert not [url for url in fetcher.asked if "?m=" in url]
    assert report.capped is False
    assert report.exhaustive is True  # выдача кончилась раньше, чем набралось 600


def test_collector_stops_at_the_limit(tyumen) -> None:
    fetcher = PagedSearch(pages=50)
    report = TwoGisCollector(fetcher).collect(SearchRequest(query="магазин", city=tyumen, limit=30, deep=False))
    assert len(report.companies) == 30
    assert len(search_pages(fetcher)) == 10  # по три фирмы на странице
    assert report.exhaustive is False


def test_a_page_without_new_companies_is_not_the_end(tyumen) -> None:
    """В глубине выдачи бывают страницы из одних домов и повторов — за ними выдача продолжается."""
    fetcher = PagedSearch(pages=6, repeat=frozenset({3}))
    report = TwoGisCollector(fetcher).collect(SearchRequest(query="магазин", city=tyumen, limit=600, deep=False))
    assert len(search_pages(fetcher)) == 6
    assert len(report.companies) == 5 * 3


def test_several_empty_pages_in_a_row_end_the_list(tyumen) -> None:
    fetcher = PagedSearch(pages=20, repeat=frozenset({2, 3, 4, 5, 6}))
    TwoGisCollector(fetcher).collect(SearchRequest(query="магазин", city=tyumen, limit=600, deep=False))
    assert len(search_pages(fetcher)) == 4  # первая и три пустых подряд


def test_a_broken_page_means_the_list_was_not_read_to_the_end(tyumen) -> None:
    """Без этого «нет в 2ГИС» писалось бы фирмам, до которых сбор просто не дошёл."""
    fetcher = PagedSearch(pages=8, broken=frozenset({3}))
    report = TwoGisCollector(fetcher).collect(SearchRequest(query="магазин", city=tyumen, limit=600, deep=False))
    assert len(report.companies) == 2 * 3
    assert report.exhaustive is False


def test_collector_notices_when_the_server_repeats_the_first_page(tyumen, twogis_pages) -> None:
    """Так 2ГИС вёл себя до ноября 2026: вместо следующей страницы — первая. Это потолок, а не конец."""
    fetcher = FakeFetcher(twogis_pages)
    report = TwoGisCollector(fetcher).collect(SearchRequest(query="кофейня", city=tyumen, limit=3, deep=False))
    assert len(report.companies) == 3
    assert len(search_pages(fetcher)) == 1  # трёх хватило — дальше не листал
    report = TwoGisCollector(FakeFetcher(twogis_pages)).collect(
        SearchRequest(query="кофейня", city=tyumen, limit=50, deep=False)
    )
    assert report.capped is True
    assert report.exhaustive is False


def test_if_the_ceiling_returns_the_city_is_cut_into_tiles(tyumen) -> None:
    fetcher = PagedSearch(pages=21, ceiling=5)
    report = TwoGisCollector(fetcher).collect(SearchRequest(query="магазин", city=tyumen, limit=200, deep=False))
    tiled = [url for url in fetcher.asked if "?m=" in url]
    assert tiled, "если выдача снова обрывается, город должен резаться на участки"
    assert all("%2F" in url for url in tiled)  # зум передан вместе с центром
    # Участки считаются по настоящему потолку: 200 мест при 5 страницах по 12 — семь участков с запасом.
    assert len({url.split("?m=")[1] for url in tiled}) == len(tiles_for(region_bounds(TYUMEN_STATE), 7))
    assert report.capped is True
    assert len(report.companies) > 5 * 3


def test_the_number_of_tiles_can_be_set_by_hand(tyumen) -> None:
    fetcher = PagedSearch(pages=21, ceiling=2)
    TwoGisCollector(fetcher).collect(SearchRequest(query="магазин", city=tyumen, limit=600, deep=False, tiles=4))
    expected = len(tiles_for(region_bounds(TYUMEN_STATE), 4))
    assert len({url.split("?m=")[1] for url in fetcher.asked if "?m=" in url}) == expected


def test_collector_opens_cards_when_asked(tyumen, twogis_pages) -> None:
    fetcher = FakeFetcher(twogis_pages)
    report = TwoGisCollector(fetcher).collect(
        SearchRequest(query="кофейня", city=tyumen, limit=10, deep=True)
    )
    assert sum(1 for url in fetcher.asked if "/firm/" in url) == 3
    # Сохранённая карточка одна, поэтому контакты достаются той фирме, чей номер в ней записан:
    # совпадение проверяется по идентификатору, а не по порядку ответов.
    assert report.cards == 1
    with_contacts = [company for company in report.companies if company.emails]
    assert [company.name for company in with_contacts] == ["Ола Ола"]
    assert with_contacts[0].emails == ("ola.ola@mail.ru",)


def test_deep_collection_can_be_switched_off(tyumen, twogis_pages) -> None:
    fetcher = FakeFetcher(twogis_pages)
    TwoGisCollector(fetcher).collect(SearchRequest(query="кофейня", city=tyumen, limit=10, deep=False))
    assert not [url for url in fetcher.asked if "/firm/" in url]


def test_source_description_tells_what_2gis_can_give() -> None:
    assert TwoGis.key == "2gis"
    assert TwoGis.can_give(EMAIL) is True  # ради почты всё и затевалось
    assert TwoGis.page_size == PAGE_SIZE
