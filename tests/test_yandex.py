"""Разбор страниц Яндекс Карт и поведение сборщика."""

from __future__ import annotations

import pytest
from conftest import FakeFetcher, fixture

from mapsparser.http import FetchError
from mapsparser.models import EMAIL, PHONE, TELEGRAM, WEBSITE
from mapsparser.sources import SearchRequest, Yandex
from mapsparser.sources.yandex import (
    PAGE_SIZE,
    YandexCollector,
    company_from,
    links_from,
    parse_state,
    results_of,
)


def test_parse_state_takes_the_largest_json_block() -> None:
    state = parse_state(fixture("yandex_search.html"))
    assert results_of(state)["totalResultCount"] == 45  # маленький блок рядом не перепутан


def test_parse_state_complains_when_the_format_changes() -> None:
    with pytest.raises(FetchError, match="формат сайта"):
        parse_state("<html><body>ничего похожего</body></html>")


def test_collection_cards_are_not_firms(tyumen) -> None:
    items = results_of(parse_state(fixture("yandex_search.html")))["items"]
    assert company_from(items[0], tyumen) is None  # подборка «Лучшие кофейни»


def test_search_item_already_carries_the_contacts(tyumen) -> None:
    items = results_of(parse_state(fixture("yandex_search.html")))["items"]
    company = company_from(items[1], tyumen)
    assert company.name == "Ола Ола"
    assert company.phones == ("+73452666707",)
    assert company.websites == ("https://ola-ola.ru",)
    assert [link.kind for link in company.socials] == [TELEGRAM]
    assert company.detailed is True  # карточку открывать не нужно


def test_coordinates_come_longitude_first(tyumen) -> None:
    items = results_of(parse_state(fixture("yandex_search.html")))["items"]
    company = company_from(items[1], tyumen)
    assert 57.0 < company.lat < 58.0
    assert 65.0 < company.lon < 66.0


def test_rating_is_rounded(tyumen) -> None:
    items = results_of(parse_state(fixture("yandex_search.html")))["items"]
    company = company_from(items[1], tyumen)
    assert company.rating == 4.8  # приходит 4.800000190734863
    assert company.reviews == 130
    assert company.photos == 81
    assert company.verified_owner is True


def test_unverified_card_is_remembered(tyumen) -> None:
    items = results_of(parse_state(fixture("yandex_search.html")))["items"]
    company = company_from(items[2], tyumen)
    assert company.verified_owner is False


def test_links_ignore_broken_entries() -> None:
    assert links_from({"phones": [{"value": "не телефон"}], "urls": ["не адрес"], "socialLinks": [{}]}) == ()


def test_collector_skips_other_cities(tyumen, yandex_pages) -> None:
    fetcher = FakeFetcher(yandex_pages)
    report = YandexCollector(fetcher).collect(SearchRequest(query="кофейня", city=tyumen, limit=50))
    names = {company.name for company in report.companies}
    assert names == {"Ола Ола", "Прокофьев"}
    assert "Чужой город" not in names  # Заводоуковск в отчёт по Тюмени не попадает


def test_collector_stops_when_the_page_repeats_itself(tyumen, yandex_pages) -> None:
    fetcher = FakeFetcher(yandex_pages)
    YandexCollector(fetcher).collect(SearchRequest(query="кофейня", city=tyumen, limit=500))
    assert len(fetcher.asked) == 2  # вторая страница без новых фирм — листать дальше незачем
    assert "page=2" in fetcher.asked[1]


def test_city_goes_into_the_query_text(tyumen, yandex_pages) -> None:
    """Яндексу не нужен код города — достаточно названия в запросе."""
    fetcher = FakeFetcher(yandex_pages)
    YandexCollector(fetcher).collect(SearchRequest(query="кофейня", city=tyumen, limit=10))
    assert "%D0%A2%D1%8E%D0%BC%D0%B5%D0%BD%D1%8C" in fetcher.asked[0]


def test_card_adds_what_the_list_was_missing(tyumen, yandex_pages) -> None:
    fetcher = FakeFetcher(yandex_pages)
    collector = YandexCollector(fetcher)
    report = collector.collect(SearchRequest(query="кофейня", city=tyumen, limit=10))
    bare = next(company for company in report.companies if company.name == "Прокофьев")
    assert bare.websites == ()
    filled = collector.enrich(bare)
    assert filled.websites == ("https://prokofev-coffee.ru",)


def test_source_description_says_there_is_no_email() -> None:
    assert Yandex.key == "yandex"
    assert Yandex.can_give(PHONE) is True
    assert Yandex.can_give(WEBSITE) is True
    assert Yandex.can_give(EMAIL) is False  # почту Яндекс не публикует
    assert Yandex.page_size == PAGE_SIZE == 25
