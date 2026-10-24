"""Приведение контактов и названий к общему виду."""

from __future__ import annotations

import pytest

from mapsparser.models import EMAIL, TELEGRAM, VK, WEBSITE, WHATSAPP
from mapsparser.normalize import (
    address_key,
    classify_website,
    clean_title,
    domain,
    email,
    name_key,
    phone,
    pretty_phone,
    social_kind,
    strip_city,
    unwrap_redirect,
    website,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+7 (3452) 66‒67‒07", "+73452666707"),  # «цифровой дефис» 2ГИС
        ("8 (345) 266-67-07", "+73452666707"),
        ("3452666707", "+73452666707"),
        ("+7 922 472-01-64", "+79224720164"),
        ("", ""),
        ("нет", ""),
    ],
)
def test_phone_is_normalised(raw: str, expected: str) -> None:
    assert phone(raw) == expected


def test_pretty_phone_formats_russian_numbers() -> None:
    assert pretty_phone("+73452666707") == "+7 (345) 266-67-07"
    assert pretty_phone("+380441234567") == "+380441234567"  # чужой код оставляем как есть


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ola.Ola@MAIL.RU", "ola.ola@mail.ru"),
        ("mailto:info@example.ru", "info@example.ru"),
        (" info@example.ru ", "info@example.ru"),
        ("не почта", ""),
        ("@example.ru", ""),
    ],
)
def test_email_is_normalised(raw: str, expected: str) -> None:
    assert email(raw) == expected


def test_website_unwraps_the_2gis_redirect() -> None:
    counter = "http://link.2gis.ru/1.2/5238FB7A/online/20261001/project13/x/null/zfi?http://ola-ola.ru"
    assert unwrap_redirect(counter) == "http://ola-ola.ru"
    assert website(counter) == "http://ola-ola.ru"


def test_website_drops_www_tracking_and_trailing_slash() -> None:
    assert website("https://WWW.Example.RU/page/?utm_source=2gis&id=7") == "https://example.ru/page?id=7"
    assert website("example.ru") == "http://example.ru"
    assert website("не адрес") == ""


def test_domain_is_the_host_without_www() -> None:
    assert domain("https://www.example.ru/page") == "example.ru"
    assert domain("") == ""


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("https://vk.com/club1", VK),
        ("https://vk.ru/brut", VK),
        ("https://t.me/olaola", TELEGRAM),
        ("https://wa.me/79000000001", WHATSAPP),
        ("https://example.ru", "other"),
    ],
)
def test_social_kind_is_taken_from_the_host(url: str, kind: str) -> None:
    assert social_kind(url) == kind


def test_classify_website_sees_a_messenger_behind_a_website_field() -> None:
    """Карты часто кладут в «сайт» ссылку на телеграм — в отчёте это не сайт."""
    assert classify_website("t.me/olaola") == (TELEGRAM, "https://t.me/olaola")
    assert classify_website("https://ola-ola.ru/") == (WEBSITE, "https://ola-ola.ru")


def test_email_kind_is_separate_from_website() -> None:
    assert EMAIL != WEBSITE


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Ола Ола, кофейня", "Ола Ола"),
        ("ООО «Ромашка»", "Ромашка"),
        ("Кофе Брют", "кофе брют"),
        ("Чёрный кот", "Черный кот"),
    ],
)
def test_name_key_makes_the_same_firm_comparable(first: str, second: str) -> None:
    assert name_key(first) == name_key(second)


def test_name_key_keeps_different_firms_apart() -> None:
    assert name_key("Ола Ола") != name_key("Ола Ола Два")


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Советская ул., 55", "улица Советская, 55"),
        ("ул. Ленина, 57А", "Ленина 57а"),
        ("Профсоюзная улица, 56", "Профсоюзная ул., 56"),
    ],
)
def test_address_key_ignores_the_way_a_street_is_written(first: str, second: str) -> None:
    assert address_key(first) == address_key(second)


def test_address_key_separates_different_houses() -> None:
    assert address_key("ул. Ленина, 57") != address_key("ул. Ленина, 59")


def test_strip_city_removes_the_city_from_an_address() -> None:
    assert strip_city("Тюмень, улица Ленина, 57", "Тюмень") == "улица Ленина, 57"
    assert strip_city("улица Ленина, 57", "Тюмень") == "улица Ленина, 57"


def test_clean_title_squeezes_spaces() -> None:
    assert clean_title("  Ола  Ола  ") == "Ола Ола"
