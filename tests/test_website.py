"""Сайт фирмы как источник: почты, телефоны и состояние самого сайта."""

from __future__ import annotations

import pytest

from mapsparser.http import Page
from mapsparser.models import EMAIL, PHONE
from mapsparser.website import check, contacts_link, emails_from, has_form, is_parked, phones_from, title_of

LIVE_PAGE = """
<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ола Ола — кофейня в Тюмени</title>
<script>var sentry = "errors@sentry.io"; var logo = "logo@2x.png";</script>
<style>.a{background:url(icon@3x.svg)}</style>
</head><body>
<h1>Кофейня «Ола Ола»</h1>
<p>Пишите нам: <a href="mailto:Hello@Ola-Ola.RU">Hello@Ola-Ola.RU</a></p>
<p>Звоните: <a href="tel:+7 (3452) 66-67-07">+7 (3452) 66-67-07</a></p>
<a href="/contacts/">Контакты</a>
<form action="/order"><input type="email" name="mail"><button>Оставить заявку</button></form>
<p>Ещё адрес для заказов: zakaz@ola-ola.ru</p>
</body></html>
"""

BARE_PAGE = """
<!DOCTYPE html><html><head><title>Кофейня</title></head><body>
<h1>Кофейня «Ола Ола»</h1><p>Мы работаем каждый день с девяти утра до десяти вечера.
Приходите к нам на Профсоюзную улицу, дом пятьдесят шесть, будем очень рады гостям.</p>
<a href="/kontakty">Наши контакты</a>
</body></html>
"""

CONTACTS_PAGE = """
<!DOCTYPE html><html><head><title>Контакты</title></head><body>
<p>Почта: <a href="mailto:info@ola-ola.ru">info@ola-ola.ru</a></p>
</body></html>
"""

PARKED_PAGE = """
<!DOCTYPE html><html><head><title>Домен припаркован</title></head>
<body><p>Домен припаркован у регистратора</p></body></html>
"""


class SiteFetcher:
    """Отдаёт заранее заготовленные страницы вместо настоящих сайтов."""

    def __init__(self, pages: dict[str, Page]) -> None:
        self.pages = pages
        self.asked: list[str] = []

    def probe(self, url: str, *, timeout: float = 10.0) -> Page:
        self.asked.append(url)
        for marker, page in self.pages.items():
            if marker in url:
                return page
        raise AssertionError(f"тест не готовил сайт {url}")


def page(text: str, status: int = 200, url: str = "https://ola-ola.ru/") -> Page:
    return Page(text=text, status=status, url=url)


def test_emails_are_taken_from_links_and_text() -> None:
    found = emails_from(LIVE_PAGE)
    assert "hello@ola-ola.ru" in found  # приведена к нижнему регистру
    assert "zakaz@ola-ola.ru" in found


def test_junk_from_markup_is_not_an_email() -> None:
    found = emails_from(LIVE_PAGE)
    assert not [value for value in found if "sentry" in value]
    assert not [value for value in found if value.endswith((".png", ".svg"))]


@pytest.mark.parametrize(
    "junk",
    [
        '<a href="mailto:noreply@ola-ola.ru">письмо</a>',
        "<p>пишите на info@example.com</p>",
        '<img src="logo@2x.png">',
    ],
)
def test_obvious_non_contacts_are_skipped(junk: str) -> None:
    assert emails_from(junk) == ()


def test_phones_come_from_tel_links() -> None:
    assert phones_from(LIVE_PAGE) == ("+73452666707",)


def test_title_is_cleaned() -> None:
    assert title_of(LIVE_PAGE) == "Ола Ола — кофейня в Тюмени"


def test_form_is_found_by_markup_or_by_widget() -> None:
    assert has_form(LIVE_PAGE) is True
    assert has_form(BARE_PAGE) is False
    assert has_form('<script src="//code.jivosite.com/widget/x"></script>') is True


def test_parked_domain_is_not_a_site() -> None:
    assert is_parked(PARKED_PAGE, "Домен припаркован") is True
    assert is_parked(LIVE_PAGE, "Ола Ола") is False


def test_contacts_link_stays_on_the_same_host() -> None:
    assert contacts_link(LIVE_PAGE, "https://ola-ola.ru/") == "https://ola-ola.ru/contacts/"
    outside = '<a href="https://vk.com/olaola">Контакты</a>'
    assert contacts_link(outside, "https://ola-ola.ru/") == ""


def test_check_reads_a_living_site() -> None:
    fetcher = SiteFetcher({"ola-ola.ru": page(LIVE_PAGE)})
    report = check("https://ola-ola.ru", fetcher)
    assert report.reachable and report.alive
    assert report.https is True
    assert report.mobile is True
    assert report.form is True
    assert "hello@ola-ola.ru" in report.emails
    assert report.phones == ("+73452666707",)
    assert report.pages == 1
    assert report.summary == "в порядке"


def test_check_opens_the_contacts_page_when_the_main_one_has_no_email() -> None:
    fetcher = SiteFetcher({
        "ola-ola.ru/kontakty": page(CONTACTS_PAGE, url="https://ola-ola.ru/kontakty"),
        "ola-ola.ru": page(BARE_PAGE),
    })
    report = check("https://ola-ola.ru", fetcher)
    assert report.emails == ("info@ola-ola.ru",)
    assert report.pages == 2
    assert len(fetcher.asked) == 2  # не больше двух запросов на сайт


def test_check_does_not_wander_further_than_two_pages() -> None:
    fetcher = SiteFetcher({"ola-ola.ru": page(BARE_PAGE)})
    report = check("https://ola-ola.ru", fetcher)
    assert report.emails == ()
    assert len(fetcher.asked) <= 2


def test_dead_site_is_a_result_not_a_failure() -> None:
    fetcher = SiteFetcher({"ola-ola.ru": page("", status=500)})
    report = check("https://ola-ola.ru", fetcher)
    assert report.reachable is False
    assert report.alive is False
    assert "500" in report.summary


def test_site_without_https_and_without_viewport_is_described() -> None:
    fetcher = SiteFetcher({"ola-ola.ru": page(BARE_PAGE, url="http://ola-ola.ru/")})
    report = check("http://ola-ola.ru", fetcher)
    assert report.https is False
    assert report.mobile is False
    assert report.summary == "без https, не для телефона, без формы заявки"


def test_parked_site_counts_as_missing() -> None:
    fetcher = SiteFetcher({"ola-ola.ru": page(PARKED_PAGE)})
    report = check("https://ola-ola.ru", fetcher)
    assert report.reachable is True
    assert report.alive is False
    assert report.summary == "заглушка вместо сайта"


def test_link_kinds_used_by_the_pipeline_exist() -> None:
    assert EMAIL == "email"
    assert PHONE == "phone"
