"""Фирмы из сохранённых страниц — для снимков окна и примера отчёта.

Берётся всё из tests/fixtures, то есть без сети и всегда одинаково. Контакты там
выдуманы: примеры лежат в открытом репозитории, настоящие номера и почты в него
попадать не должны.
"""

from __future__ import annotations

from pathlib import Path

from mapsparser.cities import City
from mapsparser.gaps import Context, apply
from mapsparser.merge import merge
from mapsparser.pipeline import Result, Settings
from mapsparser.sources import SearchRequest, TwoGis, Yandex
from mapsparser.sources.twogis import TwoGisCollector
from mapsparser.sources.yandex import YandexCollector

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
CITY = City(name="Тюмень", alias="tyumen", region="Тюменская область")


class SavedPages:
    """Загрузчик, который берёт страницы из tests/fixtures вместо сети."""

    def __init__(self) -> None:
        self.pages = {
            "/firm/": (FIXTURES / "2gis_firm.html").read_text(encoding="utf-8"),
            "/search/": (FIXTURES / "2gis_search.html").read_text(encoding="utf-8"),
            "2gis.ru/tyumen": (FIXTURES / "2gis_search.html").read_text(encoding="utf-8"),
            "maps/?text=": (FIXTURES / "yandex_search.html").read_text(encoding="utf-8"),
        }

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> str:  # noqa: ARG002
        for marker, text in self.pages.items():
            if marker in url:
                return text
        raise AssertionError(f"нет сохранённой страницы для {url}")

    def check_stop(self) -> None:
        return


def demo_result() -> Result:
    """Готовый результат сбора: четыре фирмы, одна из них видна в обеих картах."""
    fetcher = SavedPages()
    request = SearchRequest(query="кофейня", city=CITY, limit=50, deep=True)
    companies = list(TwoGisCollector(fetcher).collect(request).companies)
    companies += list(YandexCollector(fetcher).collect(request).companies)
    context = Context(sources=(TwoGis, Yandex), exhaustive=frozenset({"2gis", "yandex"}))
    return Result(
        settings=Settings(query="кофейня", city=CITY, sources=[TwoGis, Yandex]),
        places=apply(merge(companies), context),
        context=context,
    )
