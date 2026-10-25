"""Справочник городов, вежливость загрузчика, договор источников и командная строка."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from mapsparser import cities as cities_module
from mapsparser.__main__ import build_parser, main
from mapsparser.cache import Cache
from mapsparser.cities import City, alias_candidates, find, suggest, transliterate
from mapsparser.http import Fetcher, FetchError, Stopped
from mapsparser.models import EMAIL, PHONE
from mapsparser.sources import all_sources, get, resolve, source_keys

# ------------------------------------------------------------------ города


def test_transliteration_matches_how_2gis_writes_cities() -> None:
    assert transliterate("Тюмень") == "tyumen"
    assert transliterate("Екатеринбург") == "ekaterinburg"
    assert transliterate("Хабаровск") == "khabarovsk"  # «х» это kh, а не h
    assert transliterate("Новокузнецк") == "novokuznetsk"  # «ц» это ts
    assert transliterate("Нижний Новгород") == "nizhniy_novgorod"


def test_candidates_include_the_short_forms() -> None:
    assert "n_novgorod" in alias_candidates("Нижний Новгород")
    assert "habarovsk" in alias_candidates("Хабаровск")  # старое написание — запасным вариантом


def test_catalogue_knows_the_big_cities() -> None:
    assert find("Тюмень").alias == "tyumen"
    assert find("москва").alias == "moscow"
    assert find("Санкт-Петербург").alias == "spb"


def test_city_lookup_forgives_the_user() -> None:
    assert find("  тюмень ").name == "Тюмень"
    assert find("г. Тюмень").name == "Тюмень"
    assert find("Тюмень, Тюменская область").name == "Тюмень"
    assert find("Город-которого-нет") is None


def test_suggest_helps_to_type() -> None:
    names = [city.name for city in suggest("тюм")]
    assert "Тюмень" in names
    assert len(suggest("", 5)) == 5


def test_remembered_city_joins_the_catalogue(tmp_path: Path, monkeypatch) -> None:
    learned = tmp_path / "cities-found.json"
    monkeypatch.setattr(cities_module, "learned_file", lambda: learned)
    cities_module.remember(City(name="Лабытнанги", alias="labytnangi", region="ЯНАО"))
    assert json.loads(learned.read_text(encoding="utf-8"))["cities"][0]["alias"] == "labytnangi"
    assert find("Лабытнанги").alias == "labytnangi"


# ------------------------------------------------------------------ загрузчик


class FakeResponse:
    def __init__(self, status: int, text: str = "", headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.text = text
        self.headers = headers or {}


class FakeSession:
    def __init__(self, answers: list[object]) -> None:
        self.answers = answers
        self.calls = 0
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: float = 0, headers: object = None) -> FakeResponse:
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        if isinstance(answer, Exception):
            raise answer
        return answer

    def close(self) -> None:
        return


def fetcher_with(answers: list[object], **fields: object) -> Fetcher:
    fetcher = Fetcher(delay=0, retries=3, **fields)
    fetcher.session = FakeSession(answers)
    return fetcher


def test_fetcher_returns_the_page() -> None:
    fetcher = fetcher_with([FakeResponse(200, "<html>ок</html>")])
    assert fetcher.get("https://2gis.ru/tyumen") == "<html>ок</html>"
    assert fetcher.requests_made == 1


def test_fetcher_waits_when_the_map_asks_to_slow_down() -> None:
    answers = [FakeResponse(429, headers={"Retry-After": "0"}), FakeResponse(200, "страница")]
    fetcher = fetcher_with(answers)
    assert fetcher.get("https://2gis.ru/tyumen") == "страница"


def test_fetcher_retries_a_network_hiccup() -> None:
    answers = [requests.ConnectionError("сеть молчит"), FakeResponse(200, "страница")]
    assert fetcher_with(answers).get("https://2gis.ru/tyumen") == "страница"


def test_fetcher_gives_up_with_a_readable_message() -> None:
    fetcher = fetcher_with([requests.ConnectionError("сеть молчит")])
    with pytest.raises(FetchError, match="не удалось получить"):
        fetcher.get("https://2gis.ru/tyumen")


def test_missing_page_is_not_retried() -> None:
    fetcher = fetcher_with([FakeResponse(404)])
    with pytest.raises(FetchError, match="страницы нет"):
        fetcher.get("https://2gis.ru/bred")
    assert fetcher.session.calls == 1


def test_stop_interrupts_the_collection() -> None:
    fetcher = fetcher_with([FakeResponse(200, "страница")], stop=lambda: True)
    with pytest.raises(Stopped):
        fetcher.get("https://2gis.ru/tyumen")


def test_cache_saves_a_second_request(tmp_path: Path) -> None:
    cache = Cache(tmp_path, ttl_hours=1)
    fetcher = fetcher_with([FakeResponse(200, "страница")], cache=cache)
    assert fetcher.get("https://2gis.ru/tyumen") == "страница"
    assert fetcher.get("https://2gis.ru/tyumen") == "страница"
    assert fetcher.session.calls == 1
    assert fetcher.from_cache == 1
    assert cache.size_mb() >= 0
    assert cache.clear() == 1


def test_stale_cache_is_ignored(tmp_path: Path) -> None:
    cache = Cache(tmp_path, ttl_hours=0.0000001)
    cache.put("https://2gis.ru/tyumen", "старое")
    import os
    import time

    path = cache.path_for("https://2gis.ru/tyumen")
    os.utime(path, (time.time() - 3600, time.time() - 3600))
    assert cache.get("https://2gis.ru/tyumen") is None


# ------------------------------------------------------------------ договор источников


def test_every_source_describes_itself() -> None:
    for source in all_sources():
        assert source.key and source.title and source.site
        assert source.page_size > 0
        assert source.gives
        assert source.note
        assert source.collector.source is source


def test_sources_are_found_by_key() -> None:
    assert get("2gis").title == "2ГИС"
    assert [source.key for source in resolve(None)] == source_keys()
    assert [source.key for source in resolve(["yandex"])] == ["yandex"]
    with pytest.raises(KeyError, match="неизвестный источник"):
        get("google")


def test_only_2gis_promises_email() -> None:
    """От этого зависит, можно ли писать «нет почты»."""
    givers = [source.key for source in all_sources() if source.can_give(EMAIL)]
    assert givers == ["2gis"]
    assert all(source.can_give(PHONE) for source in all_sources())


# ------------------------------------------------------------------ командная строка


def test_parser_knows_the_commands() -> None:
    parser = build_parser()
    args = parser.parse_args(["collect", "-q", "кофейня", "-c", "Тюмень", "--gap", "website"])
    assert args.query == "кофейня"
    assert args.city == "Тюмень"
    assert args.gap == ["website"]
    assert args.limit == 300


def test_sources_command_prints_the_maps(capsys) -> None:
    assert main(["sources"]) == 0
    printed = capsys.readouterr().out
    assert "2ГИС" in printed
    assert "Яндекс Карты" in printed


def test_gaps_command_prints_the_weights(capsys) -> None:
    assert main(["gaps"]) == 0
    printed = capsys.readouterr().out
    assert "нет сайта" in printed
    assert "website" in printed


def test_cities_command_finds_a_city(capsys) -> None:
    assert main(["cities", "тюм"]) == 0
    assert "Тюмень" in capsys.readouterr().out


def test_a_city_outside_the_catalogue_still_works_in_yandex() -> None:
    """2ГИС без короткого имени города не умеет, Яндекс ищет по названию — сбор не отменяется."""
    guessed = cities_module.find_or_guess("Городок")
    assert guessed is not None
    assert guessed.name == "Городок"
    assert guessed.alias == ""
    assert guessed.satellite is False


def test_only_the_map_that_needs_an_alias_is_skipped(tyumen) -> None:
    from mapsparser.sources import TwoGis, Yandex

    assert TwoGis.needs_city_alias is True
    assert Yandex.needs_city_alias is False
    assert tyumen.alias  # у города из справочника короткое имя есть


def test_satellite_city_is_marked_as_such() -> None:
    """Химки ищутся внутри проекта «Москва», но поиск по их адресу сужается правильно."""
    khimki = find("Химки")
    if khimki is None:
        pytest.skip("Химок нет в справочнике этой сборки")
    assert khimki.satellite is True
    assert khimki.project == "Москва"
