"""Ниши: несколько запросов вместо одного слова."""

from __future__ import annotations

import pytest

from mapsparser.__main__ import main
from mapsparser.niches import MIN_PER_QUERY, find, load_niches, names, queries_for, share
from mapsparser.pipeline import Settings
from mapsparser.sources import TwoGis, Yandex

from conftest import FakeFetcher


def test_niches_are_shipped_with_the_program() -> None:
    found = load_niches()
    assert len(found) >= 20
    assert "Автосервисы" in names()
    for niche in found:
        assert niche.queries
        assert all(query.strip() for query in niche.queries)


def test_a_niche_is_more_than_one_word() -> None:
    """Фирма называет себя «СТО», а ищут её как «автосервис» — ради этого ниши и нужны."""
    niche = find("Автосервисы")
    assert "автосервис" in niche.queries
    assert "СТО" in niche.queries
    assert len(niche.queries) >= 4


def test_niche_lookup_forgives_case() -> None:
    assert find("автосервисы").name == "Автосервисы"
    assert find("АВТОСЕРВИСЫ").name == "Автосервисы"
    assert find("такой ниши нет") is None


def test_a_plain_word_stays_a_single_query() -> None:
    assert queries_for("кофейня") == ("кофейня",)
    assert queries_for("  ") == ()


def test_a_niche_name_turns_into_its_queries() -> None:
    assert queries_for("Автосервисы") == find("Автосервисы").queries


def test_limit_is_shared_between_queries() -> None:
    """Иначе ниша из шести слов собирала бы вшестеро дольше обещанного."""
    assert share(300, 1) == 300
    assert share(300, 5) == 60
    assert share(60, 6) == MIN_PER_QUERY  # ниже этого собирать бессмысленно


def test_settings_take_queries_from_the_niche(tyumen) -> None:
    settings = Settings(query="Автосервисы", city=tyumen)
    assert len(settings.all_queries()) >= 4
    assert Settings(query="кофейня", city=tyumen).all_queries() == ("кофейня",)
    explicit = Settings(query="что угодно", city=tyumen, queries=("одно", "другое"))
    assert explicit.all_queries() == ("одно", "другое")


def test_pipeline_asks_every_query_of_the_niche(tyumen, monkeypatch, twogis_pages, yandex_pages) -> None:
    from mapsparser.pipeline import run

    fetcher = FakeFetcher({**twogis_pages, **yandex_pages})
    monkeypatch.setattr("mapsparser.pipeline.Fetcher", lambda **_kwargs: fetcher)
    settings = Settings(
        query="кофейня",
        queries=("кофейня", "пекарня"),
        city=tyumen,
        sources=[TwoGis, Yandex],
        limit=50,
        use_cache=False,
        check_sites=False,
    )
    run(settings)
    assert any("%D0%BF%D0%B5%D0%BA%D0%B0%D1%80%D0%BD%D1%8F" in url for url in fetcher.asked)
    assert any("%D0%BA%D0%BE%D1%84%D0%B5%D0%B9%D0%BD%D1%8F" in url for url in fetcher.asked)


def test_one_firm_found_twice_is_counted_once(tyumen, monkeypatch, twogis_pages, yandex_pages) -> None:
    """Сохранённые страницы отдают одно и то же на оба запроса — фирм должно остаться столько же."""
    from mapsparser.pipeline import run

    fetcher = FakeFetcher({**twogis_pages, **yandex_pages})
    monkeypatch.setattr("mapsparser.pipeline.Fetcher", lambda **_kwargs: fetcher)
    base = {"city": tyumen, "sources": [TwoGis, Yandex], "limit": 50, "use_cache": False, "check_sites": False}
    one = run(Settings(query="кофейня", **base))
    two = run(Settings(query="кофейня", queries=("кофейня", "пекарня"), **base))
    assert len(two.places) == len(one.places)


def test_niches_command_prints_the_queries(capsys) -> None:
    assert main(["niches"]) == 0
    printed = capsys.readouterr().out
    assert "Автосервисы" in printed
    assert "СТО" in printed


def test_unknown_niche_is_explained(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["collect", "-c", "Тюмень", "--niche", "Космодромы"])
    assert exit_info.value.code == 2
    assert "не нашлась" in capsys.readouterr().err
