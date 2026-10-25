"""ИНН из ЕГРЮЛ: лучше пустая клетка, чем чужой ИНН."""

from __future__ import annotations

import json
from datetime import date

from mapsparser.egrul import Entity, clean_name, lookup, pick, search

ROWS = {
    "surf": {
        "i": "7203451668", "o": "1187232016330", "p": "720301001", "k": "ul",
        "n": 'ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "СЁРФ КОФЕ ТЮМЕНЬ"',
        "c": 'ООО "СЁРФ КОФЕ ТЮМЕНЬ"', "g": "ДИРЕКТОР: Иванов Иван Иванович",
        "r": "13.06.2018", "rn": "Тюменская область",
    },
    "surf_kurgan": {
        "i": "4501000000", "o": "1184500000000", "k": "ul",
        "n": 'ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "СЁРФ КОФЕ ТЮМЕНЬ"',
        "c": 'ООО "СЁРФ КОФЕ ТЮМЕНЬ"', "r": "01.02.2019", "rn": "Курганская область",
    },
    "other": {
        "i": "7203308700", "o": "1147232019428", "k": "ul",
        "n": 'ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "ТОЧКА КОФЕ ТЮМЕНЬ"',
        "c": 'ООО "ТОЧКА КОФЕ ТЮМЕНЬ"', "r": "16.04.2014", "rn": "Тюменская область",
    },
    "person": {
        "i": "720300000000", "o": "320723200000000", "k": "ip",
        "n": "ИНДИВИДУАЛЬНЫЙ ПРЕДПРИНИМАТЕЛЬ ПЕТРОВ ПЁТР ПЕТРОВИЧ",
        "c": "ИП ПЕТРОВ ПЁТР ПЕТРОВИЧ", "r": "05.05.2020", "rn": "Тюменская область",
    },
}


class FakeRegistry:
    """Поддельный реестр: сперва выдаёт талон, потом строки по нему."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[str] = []

    def post(self, url: str, data: dict[str, str], *, timeout: float = 30.0) -> str:
        self.calls.append(data.get("query", ""))
        return json.dumps({"t": "ТАЛОН", "captchaRequired": False})

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> str:
        return json.dumps({"rows": self.rows})


def entity(key: str) -> Entity:
    row = ROWS[key]
    return Entity(
        inn=row["i"], ogrn=row["o"], name=row["n"], short=row["c"],
        region=row.get("rn", ""), kind=row["k"],
        registered=date(*reversed([int(part) for part in row["r"].split(".")])),
    )


def test_legal_form_and_quotes_are_stripped() -> None:
    assert clean_name('ООО "СЁРФ КОФЕ ТЮМЕНЬ"') == clean_name("Серф Кофе Тюмень")
    assert clean_name('ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "ТОЧКА"') == "точка"


def test_search_reads_the_registry_answer() -> None:
    registry = FakeRegistry([ROWS["surf"]])
    found = search("Сёрф Кофе Тюмень", registry)
    assert len(found) == 1
    assert found[0].inn == "7203451668"
    assert found[0].registered == date(2018, 6, 13)
    assert found[0].is_person is False


def test_exact_name_and_region_give_the_inn() -> None:
    chosen = pick("Сёрф Кофе Тюмень", "Тюменская область", [entity("surf"), entity("other")])
    assert chosen is not None
    assert chosen.inn == "7203451668"


def test_a_namesake_from_another_region_is_refused() -> None:
    """Тот же текст в названии, но регистрация в другом регионе — не наша фирма."""
    assert pick("Сёрф Кофе Тюмень", "Тюменская область", [entity("surf_kurgan")]) is None


def test_two_namesakes_leave_the_cell_empty() -> None:
    """Непонятно, кто из них, — значит, ИНН не приписываем никому."""
    assert pick("Сёрф Кофе Тюмень", "Тюменская область", [entity("surf"), entity("surf")]) is None


def test_a_brand_that_is_not_the_legal_name_finds_nothing() -> None:
    """На карте «Кофе Брют», в реестре «Точка Кофе Тюмень» — совпадения нет, и это правильно."""
    assert pick("Кофе Брют", "Тюменская область", [entity("other")]) is None


def test_lookup_puts_the_city_into_the_query() -> None:
    registry = FakeRegistry([ROWS["surf"]])
    found = lookup("Сёрф Кофе Тюмень", "Тюмень", "Тюменская область", registry)
    assert found is not None
    assert registry.calls == ["Сёрф Кофе Тюмень Тюмень"]


def test_an_entrepreneur_is_marked_as_a_person() -> None:
    """У ИП за названием стоит живой человек — это важно помнить при рассылках."""
    assert entity("person").is_person is True


def test_age_shows_how_young_the_firm_is() -> None:
    young = entity("surf")
    assert young.age_days(date(2018, 7, 13)) == 30
    assert Entity().age_days() is None


def test_broken_answer_does_not_break_the_search() -> None:
    class Broken(FakeRegistry):
        def get(self, url: str, *, headers: dict[str, str] | None = None) -> str:
            return "совсем не json"

    assert search("что-нибудь", Broken([])) == []
