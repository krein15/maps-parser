"""Весь путь сбора: две карты → сведение → пробелы → фильтры."""

from __future__ import annotations

import pytest
from conftest import FakeFetcher

from mapsparser.pipeline import Settings, run
from mapsparser.sources import TwoGis, Yandex


@pytest.fixture
def both_maps(monkeypatch, twogis_pages, yandex_pages) -> FakeFetcher:
    """Подменяет загрузчик на поддельный: ни один тест не должен ходить в сеть."""
    fetcher = FakeFetcher({**twogis_pages, **yandex_pages})
    monkeypatch.setattr("mapsparser.pipeline.Fetcher", lambda **_kwargs: fetcher)
    return fetcher


def settings(tyumen, **fields: object) -> Settings:
    # История по умолчанию пишется рядом с настройками пользователя; в тестах — никуда.
    base = {
        "query": "кофейня",
        "city": tyumen,
        "sources": [TwoGis, Yandex],
        "limit": 50,
        "use_cache": False,
        "check_sites": False,  # проверка сайтов включается отдельным тестом
        "remember": False,
    }
    return Settings(**{**base, **fields})


def test_run_collects_both_maps_and_merges_them(tyumen, both_maps) -> None:
    result = run(settings(tyumen))
    names = sorted(place.name for place in result.places)
    assert names == ["Кофе и Точка", "Ола Ола", "Прокофьев", "Раф"]
    ola = next(place for place in result.places if place.name == "Ола Ола")
    assert set(ola.by_source) == {"2gis", "yandex"}  # одна фирма из двух карт
    assert result.in_both == 1


def test_contacts_of_both_maps_end_up_in_one_row(tyumen, both_maps) -> None:
    result = run(settings(tyumen))
    ola = next(place for place in result.places if place.name == "Ола Ола")
    assert ola.emails == ("ola.ola@mail.ru",)  # только 2ГИС знает почту
    assert ola.websites == ("https://ola-ola.ru",)  # https из Яндекса победил http из 2ГИС
    assert ola.phones == ("+73452666707",)


def test_the_report_counts_requests_and_sources(tyumen, both_maps) -> None:
    result = run(settings(tyumen))
    assert set(result.reports) == {"2gis", "yandex"}
    assert result.requests == both_maps.requests_made
    assert result.collected == sum(len(report.companies) for report in result.reports.values())


def test_only_one_map_can_be_asked(tyumen, both_maps) -> None:
    result = run(settings(tyumen, sources=[Yandex]))
    assert set(result.reports) == {"yandex"}
    assert all("2gis" not in place.by_source for place in result.places)
    assert not [url for url in both_maps.asked if "2gis.ru" in url]


def test_a_required_gap_filters_the_list(tyumen, both_maps) -> None:
    result = run(settings(tyumen, required_gaps=("website",)))
    assert result.places
    assert all(not place.websites for place in result.places)
    assert all("нет сайта" in place.gaps for place in result.places)


def test_min_score_filters_the_list(tyumen, both_maps) -> None:
    everything = run(settings(tyumen))
    best = max(place.score for place in everything.places)
    narrowed = run(settings(tyumen, min_score=best))
    assert narrowed.places
    assert all(place.score >= best for place in narrowed.places)


def test_stop_cuts_the_collection_short(tyumen, both_maps) -> None:
    result = run(settings(tyumen), stop=lambda: True)
    assert result.stopped is True
    assert not result.places
    assert not both_maps.asked  # до карт дело не дошло


def test_log_tells_what_is_happening(tyumen, both_maps) -> None:
    lines: list[str] = []
    run(settings(tyumen), log=lines.append)
    assert any("2ГИС" in line for line in lines)
    assert any("Яндекс" in line for line in lines)
    assert any("Готово" in line for line in lines)


SITE_PAGE = """
<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width">
<title>Ола Ола</title></head><body>
<a href="mailto:zakaz@ola-ola.ru">написать</a>
<form><input type="email"></form>
</body></html>
"""


def test_site_check_adds_emails_the_maps_did_not_have(tyumen, monkeypatch, twogis_pages, yandex_pages) -> None:
    """Главное ради чего ходим на сайт: почта, которой нет ни на одной карте."""
    fetcher = FakeFetcher({**twogis_pages, **yandex_pages}, sites={"ola-ola.ru": SITE_PAGE})
    monkeypatch.setattr("mapsparser.pipeline.Fetcher", lambda **_kwargs: fetcher)
    result = run(settings(tyumen, check_sites=True))
    ola = next(place for place in result.places if place.name == "Ола Ола")
    assert "zakaz@ola-ola.ru" in ola.emails
    assert ola.from_site("email") == ("zakaz@ola-ola.ru",)
    assert ola.site is not None and ola.site.alive
    assert result.sites_checked == 1  # сайт был только у одной фирмы


def test_site_that_does_not_open_becomes_a_gap(tyumen, monkeypatch, twogis_pages, yandex_pages) -> None:
    fetcher = FakeFetcher({**twogis_pages, **yandex_pages}, sites={})  # ни один сайт не отвечает
    monkeypatch.setattr("mapsparser.pipeline.Fetcher", lambda **_kwargs: fetcher)
    result = run(settings(tyumen, check_sites=True))
    ola = next(place for place in result.places if place.name == "Ола Ола")
    assert "сайт не открывается" in ola.gaps
    assert "нет сайта" not in ola.gaps  # сайт-то есть, он просто мёртвый


def test_sites_are_not_touched_when_the_check_is_off(tyumen, both_maps) -> None:
    run(settings(tyumen, check_sites=False))
    assert not both_maps.probed
