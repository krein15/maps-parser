"""Колонка «чего у фирмы нет»: то, ради чего программа отличается от прочих парсеров карт."""

from __future__ import annotations

from mapsparser.gaps import Context, apply, codes_for, evaluate, hints_for, reachable
from mapsparser.models import EMAIL, PHONE, WEBSITE, Company, Link, Place
from mapsparser.sources import TwoGis, Yandex

BOTH = Context(sources=(TwoGis, Yandex), exhaustive=frozenset({"2gis", "yandex"}))


def place(*companies: Company, **fields: object) -> Place:
    return Place(
        name=fields.get("name", "Ола Ола"),
        address=fields.get("address", "Профсоюзная улица, 56"),
        by_source={company.source: company for company in companies},
    )


def company(source: str, **fields: object) -> Company:
    base = {"source": source, "source_id": "1", "name": "Ола Ола", "address": "Профсоюзная улица, 56"}
    return Company(**{**base, **fields})


def test_no_email_is_claimed_only_when_2gis_saw_the_firm() -> None:
    """Яндекс почту не публикует: по его данным «нет почты» — это пробел источника, а не фирмы."""
    only_yandex = place(company("yandex", links=(Link(PHONE, "+79000000001"),)))
    assert "email" not in codes_for(only_yandex, BOTH)

    with_2gis = place(company("2gis", links=(Link(PHONE, "+79000000001"),)))
    assert "email" in codes_for(with_2gis, BOTH)


def test_email_found_by_2gis_closes_the_gap() -> None:
    found = place(company("2gis", links=(Link(EMAIL, "ola@mail.ru"),)))
    assert "email" not in codes_for(found, BOTH)


def test_no_website_is_the_heaviest_gap() -> None:
    without = place(company("2gis", links=(Link(PHONE, "+79000000001"),)))
    titles, score = evaluate(without, BOTH)
    assert "нет сайта" in titles
    assert score >= 30


def test_missing_in_a_map_needs_an_exhaustive_collection() -> None:
    """Пока сбор упирался в заданное число фирм, отсутствие в карте ничего не доказывает."""
    only_2gis = place(company("2gis", links=(Link(PHONE, "+79000000001"),)))
    partial = Context(sources=(TwoGis, Yandex), exhaustive=frozenset())
    assert "no_yandex" not in codes_for(only_2gis, partial)
    assert "no_yandex" in codes_for(only_2gis, BOTH)


def test_missing_in_a_map_needs_two_maps() -> None:
    alone = Context(sources=(TwoGis,), exhaustive=frozenset({"2gis"}))
    assert "no_yandex" not in codes_for(place(company("2gis")), alone)


def test_unverified_card_is_a_gap_only_when_a_map_knows_it() -> None:
    unknown = place(company("2gis", verified_owner=None, links=(Link(PHONE, "+79000000001"),)))
    assert "unverified" not in codes_for(unknown, BOTH)
    known = place(company("yandex", verified_owner=False, links=(Link(PHONE, "+79000000001"),)))
    assert "unverified" in codes_for(known, BOTH)


def test_no_reviews_and_few_reviews_do_not_overlap() -> None:
    empty = place(company("yandex", reviews=0, links=(Link(PHONE, "+79000000001"),)))
    assert "no_reviews" in codes_for(empty, BOTH)
    assert "few_reviews" not in codes_for(empty, BOTH)
    few = place(company("yandex", reviews=4, links=(Link(PHONE, "+79000000001"),)))
    assert "few_reviews" in codes_for(few, BOTH)
    assert "no_reviews" not in codes_for(few, BOTH)


def test_a_firm_nobody_can_reach_gets_no_score() -> None:
    """Пробелов много, а звонить некуда — такая строка в списке обзвона бесполезна."""
    unreachable = place(company("2gis", reviews=0, verified_owner=False))
    titles, score = evaluate(unreachable, BOTH)
    assert titles  # пробелы названы
    assert score == 0
    assert reachable(unreachable) is False


def test_score_never_goes_above_a_hundred() -> None:
    bare = place(company("2gis", reviews=0, rating=3.0, photos=0, links=(Link(PHONE, "+79000000001"),)),
                 company("yandex", reviews=0, rating=3.0, photos=0, verified_owner=False))
    _titles, score = evaluate(bare, BOTH)
    assert score <= 100


def test_apply_sorts_the_most_interesting_first() -> None:
    rich = place(company("2gis", rating=4.9, reviews=500, photos=20,
                         links=(Link(PHONE, "+79000000001"), Link(EMAIL, "a@b.ru"),
                                Link(WEBSITE, "https://a.ru"), Link("vk", "https://vk.com/a"),
                                Link("telegram", "https://t.me/a"))),
                 company("yandex", rating=4.9, reviews=500, verified_owner=True, photos=20))
    poor = place(company("2gis", rating=3.5, reviews=2, photos=0, links=(Link(PHONE, "+79000000002"),)),
                 company("yandex", rating=3.5, reviews=2, verified_owner=False, photos=0),
                 name="Кофе и Точка")
    ordered = apply([rich, poor], BOTH)
    assert ordered[0].name == "Кофе и Точка"
    assert ordered[0].score > ordered[1].score


def test_hints_explain_what_to_offer() -> None:
    assert hints_for(("нет сайта",)) == ("сделать сайт или хотя бы страницу-визитку",)
    assert hints_for(("такого пробела нет",)) == ()
