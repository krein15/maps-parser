"""Общая оснастка тестов: сохранённые страницы вместо сети.

Ни один тест не ходит в интернет. Поддельный загрузчик отдаёт страницы из
tests/fixtures и запоминает, какие адреса у него просили, — по этому списку
проверяется, что сборщик листает выдачу и открывает карточки так, как задумано.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapsparser.cities import City

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    """Загрузчик, который вместо сети берёт сохранённые страницы."""

    def __init__(self, pages: dict[str, str] | None = None, default: str = "") -> None:
        self.pages = pages or {}
        self.default = default
        self.asked: list[str] = []
        self.requests_made = 0
        self.from_cache = 0

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> str:
        self.asked.append(url)
        self.requests_made += 1
        for marker, text in self.pages.items():
            if marker in url:
                return text
        if self.default:
            return self.default
        raise AssertionError(f"тест не готовил страницу для {url}")

    def check_stop(self) -> None:
        return

    def close(self) -> None:
        return

    def __enter__(self) -> FakeFetcher:
        return self

    def __exit__(self, *_exc: object) -> None:
        return


@pytest.fixture
def tyumen() -> City:
    return City(name="Тюмень", alias="tyumen", region="Тюменская область")


@pytest.fixture
def twogis_pages() -> dict[str, str]:
    """Страницы 2ГИС: выдача, карточка и страница города (из неё берутся границы)."""
    return {
        "/firm/": fixture("2gis_firm.html"),
        "/search/": fixture("2gis_search.html"),
        "2gis.ru/tyumen": fixture("2gis_search.html"),
    }


@pytest.fixture
def yandex_pages() -> dict[str, str]:
    return {"/org/": fixture("yandex_org.html"), "maps/?text=": fixture("yandex_search.html")}
