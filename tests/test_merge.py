"""Сведение одной фирмы из двух карт — и защита от склейки филиалов."""

from __future__ import annotations

from mapsparser.merge import distance_meters, merge, same_place
from mapsparser.models import PHONE, WEBSITE, Company, Link, is_mobile


def company(source: str, name: str, address: str, lat: float | None = 57.15, lon: float | None = 65.55,
            links: tuple[Link, ...] = ()) -> Company:
    return Company(
        source=source, source_id=f"{source}-{name}-{address}", name=name, address=address,
        city="Тюмень", lat=lat, lon=lon, links=links,
    )


def test_same_firm_from_two_maps_becomes_one_row() -> None:
    first = company("2gis", "Ола Ола, кофейня", "Профсоюзная улица, 56")
    second = company("yandex", "Ола Ола", "Профсоюзная ул., 56")
    places = merge([first, second])
    assert len(places) == 1
    assert set(places[0].by_source) == {"2gis", "yandex"}


def test_addresses_written_differently_still_meet() -> None:
    assert same_place(
        company("2gis", "Кофе Брют", "Советская улица, 55"),
        company("yandex", "Кофе Брют", "Советская ул., 55"),
    )


def test_coordinates_save_the_match_when_the_address_differs() -> None:
    first = company("2gis", "Ола Ола", "Профсоюзная улица, 56", lat=57.152185, lon=65.554530)
    second = company("yandex", "Ола Ола", "рядом с ТЦ", lat=57.152190, lon=65.554540)
    assert same_place(first, second)


def test_branches_of_one_chain_stay_apart() -> None:
    """У сети один сайт и часто один телефон: склеить филиалы — соврать в отчёте."""
    site = (Link(WEBSITE, "https://brut.ru"), Link(PHONE, "+73452000000"))
    first = company("2gis", "Кофе Брют", "улица Ленина, 57", lat=57.1539, lon=65.5351, links=site)
    second = company("yandex", "Кофе Брют", "улица 50 лет Октября, 44", lat=57.1700, lon=65.5600, links=site)
    assert not same_place(first, second)
    assert len(merge([first, second])) == 2


def test_two_records_of_one_map_are_never_merged() -> None:
    first = company("2gis", "Ола Ола", "Профсоюзная улица, 56")
    second = company("2gis", "Ола Ола", "Профсоюзная улица, 56")
    assert not same_place(first, second)


def test_different_firms_at_one_address_stay_apart() -> None:
    first = company("2gis", "Ола Ола", "улица Ленина, 57")
    second = company("yandex", "Шоколадница", "улица Ленина, 57")
    assert not same_place(first, second)


def test_merged_place_keeps_contacts_of_both_maps() -> None:
    first = company("2gis", "Ола Ола", "Профсоюзная улица, 56",
                    links=(Link("email", "ola@mail.ru"), Link(PHONE, "+73452666707")))
    second = company("yandex", "Ола Ола", "Профсоюзная улица, 56",
                     links=(Link(WEBSITE, "https://ola-ola.ru"), Link(PHONE, "+73452666707")))
    place = merge([first, second])[0]
    assert place.emails == ("ola@mail.ru",)
    assert place.websites == ("https://ola-ola.ru",)
    assert place.phones == ("+73452666707",)  # один и тот же номер не удваивается


def test_http_and_https_of_one_site_are_one_site() -> None:
    first = company("2gis", "Ола Ола", "Профсоюзная улица, 56", links=(Link(WEBSITE, "http://ola-ola.ru"),))
    second = company("yandex", "Ола Ола", "Профсоюзная улица, 56", links=(Link(WEBSITE, "https://ola-ola.ru"),))
    place = merge([first, second])[0]
    assert place.websites == ("https://ola-ola.ru",)  # из двух записей остаётся защищённая


def test_rating_is_averaged_and_reviews_are_added() -> None:
    first = Company(source="2gis", source_id="1", name="Ола Ола", address="Профсоюзная улица, 56",
                    lat=57.15, lon=65.55, rating=4.8, reviews=125)
    second = Company(source="yandex", source_id="2", name="Ола Ола", address="Профсоюзная улица, 56",
                     lat=57.15, lon=65.55, rating=5.0, reviews=130)
    place = merge([first, second])[0]
    assert place.rating == 4.9
    assert place.reviews == 255


def test_distance_is_none_without_coordinates() -> None:
    assert distance_meters(company("2gis", "А", "Б", lat=None, lon=None), company("yandex", "А", "Б")) is None


def test_a_chain_point_is_marked_as_such() -> None:
    """Звонить в филиал сети бессмысленно: решение принимает центр."""
    single = company("2gis", "Ола Ола", "Профсоюзная улица, 56")
    from mapsparser.merge import place_from

    assert place_from([single]).is_chain is False

    branch = Company(source="yandex", source_id="1", name="Кофе Брют", address="улица Ленина, 57",
                     chain="Кофе Брют")
    place = place_from([branch])
    assert place.is_chain is True
    assert place.chain == "Кофе Брют"


def test_many_branches_count_as_a_chain_even_without_a_name() -> None:
    from mapsparser.merge import place_from

    many = Company(source="2gis", source_id="1", name="Ола Ола", address="Профсоюзная улица, 56", branch_count=7)
    place = place_from([many])
    assert place.branches == 7
    assert place.is_chain is True


def test_mobile_numbers_are_told_apart() -> None:
    """По мобильному пишут в мессенджер, по городскому звонят в приёмную."""
    both = company("2gis", "Ола Ола", "Профсоюзная улица, 56",
                   links=(Link(PHONE, "+73452666707"), Link(PHONE, "+79224720164")))
    from mapsparser.merge import place_from

    place = place_from([both])
    assert place.phones == ("+73452666707", "+79224720164")
    assert place.mobile_phones == ("+79224720164",)


def test_is_mobile_knows_russian_numbers() -> None:
    assert is_mobile("+79224720164") is True
    assert is_mobile("+73452666707") is False
    assert is_mobile("") is False
