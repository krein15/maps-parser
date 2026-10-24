r"""Собирает страницы для тестов — tests/fixtures/*.html.

Тесты не ходят в сеть: они разбирают сохранённые страницы. Страницы здесь не
скачаны, а собраны по тому же устройству, что у настоящих, и нарочно набиты
ловушками источников, которые обнаружились при разведке:

 - у 2ГИС состояние экранировано по правилам JavaScript, телефон разделён знаком
   U+2012, сайт спрятан за счётчиком переходов link.2gis.ru, а под видом «сайта»
   лежит ссылка на телеграм; в выдаче попадается дом, а не организация;
 - у Яндекса долгота идёт первой, рейтинг приходит с хвостом (4.800000190734863),
   среди результатов встречается подборка, а не фирма, и фирма из соседнего города.

Контакты и названия выдуманы: в открытый репозиторий настоящие не кладём.

    .venv\Scripts\python tools\make_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def firm(fid: str, name: str, ext: str, street: str, house: str, lat: float, lon: float,
         rating: float, count: int, rubric: str, promoted: bool = False) -> tuple[str, dict]:
    return fid, {
        "id": fid,
        "type": "branch",
        "name": f"{name}, {ext}",
        "name_ex": {"primary": name, "extension": ext},
        "address_name": f"{street}, {house}",
        "address": {"components": [{"street": street, "number": house, "type": "street_number"}],
                    "postcode": "625002"},
        "point": {"lat": lat, "lon": lon},
        "reviews": {"general_rating": rating, "general_review_count_with_stars": count,
                    "general_review_count": count - 2},
        "rubrics": [{"id": "162", "name": rubric, "kind": "primary"}],
        "org": {"id": str(int(fid) - 1), "branch_count": 1, "primary": name},
        "schedule": ["Mon", "Tue"],
        "city_alias": "tyumen",
        "is_promoted": promoted,
    }


def as_2gis_page(state: dict, title: str) -> str:
    """Состояние внутри одинарных кавычек: экранируем, как это делает сайт."""
    payload = json.dumps(state, ensure_ascii=False).replace("\\", "\\\\").replace("'", "\\'")
    return (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">'
        f"<title>{title}</title></head><body><div id=\"root\"></div>"
        "<script>window.__classNames=JSON.parse('[]');</script>\n"
        f"<script>\n          var initialState = JSON.parse('{payload}');\n</script>"
        "</body></html>"
    )


def as_yandex_page(state: dict, title: str) -> str:
    """Состояние — в самом большом блоке JSON; маленький рядом нужен, чтобы его не перепутали."""
    return (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">'
        f"<title>{title}</title></head><body><div id=\"root\"></div>"
        '<script type="application/json" id="small">{"config":1}</script>'
        '<script type="application/json">' + json.dumps(state, ensure_ascii=False) + "</script>"
        "</body></html>"
    )


def yandex_item(oid: str, title: str, seoname: str, street: str, house: str, lat: float, lon: float,
                rating: float, count: int, reviews: int, phone: str = "", urls: list[str] | None = None,
                socials: list[dict] | None = None, verified: bool = False, photos: int = 0,
                hours: str = "ежедневно, 08:00–22:00") -> dict:
    return {
        "type": "business",
        "id": oid,
        "title": title,
        "seoname": seoname,
        "address": f"{street}, {house}",
        "fullAddress": f"Тюмень, {street}, {house}",
        "coordinates": [lon, lat],  # долгота первой
        "phones": [{"number": phone, "type": "phone", "value": phone.replace(" ", "")}] if phone else [],
        "urls": urls or [],
        "socialLinks": socials or [],
        "businessLinks": [],
        "ratingData": {"ratingValue": rating, "ratingCount": count, "reviewCount": reviews},
        "categories": [{"id": "1", "name": "Кофейня", "class": "cafe", "pluralName": "Кофейни"}],
        "businessProperties": {"has_verified_owner": verified, "geoproduct_poi_color": "#FFA15E"},
        "photos": {"count": photos},
        "workingTimeText": hours,
        "currentWorkingStatus": {"isOpenNow": True, "text": "Открыто до 22:00"},
    }


def build_2gis_search() -> dict:
    items = dict(
        [
            firm("70000001000000001", "Ола Ола", "кофейня", "Профсоюзная улица", "56",
                 57.152185, 65.554530, 4.8, 125, "Кофейни"),
            firm("70000001000000002", "Раф", "кофейня", "улица Герцена", "63",
                 57.154000, 65.536000, 4.9, 1676, "Кофейни", promoted=True),
            firm("70000001000000003", "Кофе и Точка", "кофейня", "улица Ленина", "57А",
                 57.153997, 65.535134, 3.6, 4, "Кофейни"),
        ]
    )
    # Дом, а не организация: сборщик обязан его пропустить.
    items["1830223003800694"] = {
        "id": "1830223003800694", "type": "building", "name": "Профсоюзная улица, 56",
        "address_name": "Профсоюзная улица, 56", "point": {"lat": 57.1522, "lon": 65.5545},
    }
    return {
        "data": {
            "entity": {"profile": {key: {"data": value, "meta": {"status": "ok"}} for key, value in items.items()}},
            "search": {"profile": {"496094f2-57b7-4a80-98f4-563e5d5e0177": {"data": {
                "query": "кофейня", "total": 241, "pages": 21, "currentPage": 1,
                "searchType": 2, "hasPagesToLoad": True,
            }}}},
            "region": {"profile": {"13": {"data": {
                "id": "13", "code": "tyumen", "name": "Тюмень", "country_code": "ru",
                "bounds": "POLYGON((65.40 57.08,65.70 57.08,65.70 57.22,65.40 57.22,65.40 57.08))",
            }}}},
        },
        "session": {"isMobile": False},
    }


def build_2gis_card(search_state: dict) -> dict:
    card = dict(search_state["data"]["entity"]["profile"]["70000001000000001"]["data"])
    card["contact_groups"] = [{
        "contacts": [
            {"type": "phone", "text": "+7 (3452) 66‒67‒07", "value": "+73452666707", "code": "1"},
            {"type": "website", "text": "ola-ola.ru",
             "value": "http://link.2gis.ru/1.2/5238FB7A/online/20261001/project13/x/null/zfi?http://ola-ola.ru",
             "url": "http://link.2gis.ru/1.2/5238FB7A/x?http://ola-ola.ru", "code": "2"},
            {"type": "email", "text": "Ola.Ola@MAIL.RU", "value": "Ola.Ola@MAIL.RU", "code": "3"},
            {"type": "vkontakte", "url": "https://vk.com/club000000001",
             "text": "vk.com/club000000001", "code": "4"},
            {"type": "whatsapp", "url": "https://wa.me/79000000001?text=%D0%97%D0%B4%D1%80%D0%B0%D0%B2",
             "text": "WhatsApp", "code": "5"},
            {"type": "website", "text": "t.me/olaola", "value": "https://t.me/olaola", "code": "6"},
            {"type": "fax", "text": "+7 (3452) 66-67-08", "value": "+73452666708", "code": "7"},
        ],
        "schedule": {},
    }]
    weekday = {"working_hours": [{"from": "09:00", "to": "22:00"}]}
    weekend = {"working_hours": [{"from": "10:00", "to": "18:00"}]}
    card["schedule"] = {
        "Mon": weekday, "Tue": weekday, "Wed": weekday, "Thu": weekday, "Fri": weekday,
        "Sat": weekend, "Sun": weekend,
    }
    return {"data": {
        "entity": {"profile": {"70000001000000001": {"data": card, "meta": {"status": "ok"}}}},
        "region": search_state["data"]["region"],
    }}


def build_yandex_search() -> dict:
    items = [
        {"type": "collection", "title": "Лучшие кофейни Тюмени", "coordinates": [65.53, 57.15]},
        yandex_item("130000000000001", "Ола Ола", "ola_ola", "Профсоюзная улица", "56",
                    57.152190, 65.554540, 4.800000190734863, 130, 44,
                    phone="+7 (345) 266-67-07", urls=["https://ola-ola.ru/"],
                    socials=[{"type": "telegram", "href": "https://t.me/olaola", "readableHref": "@olaola"}],
                    verified=True, photos=81),
        yandex_item("130000000000002", "Прокофьев", "prokofev", "улица Республики", "26",
                    57.150000, 65.540000, 5, 3024, 974, phone="+79000000002", photos=12),
    ]
    stranger = yandex_item("130000000000003", "Чужой город", "chuzhoy", "улица Мира", "1",
                           56.0, 65.0, 4.0, 10, 5)
    stranger["fullAddress"] = "Заводоуковск, улица Мира, 1"
    items.append(stranger)
    return {"stack": [{"id": "serp", "results": {
        "items": items, "totalResultCount": 45, "resultsCount": 25, "pageCount": 25,
        "requestQuery": "кофейня Тюмень", "bounds": [[65.48, 57.11], [65.61, 57.18]],
    }}], "config": {"requestId": "test"}}


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    search = build_2gis_search()
    (FIXTURES / "2gis_search.html").write_text(
        as_2gis_page(search, "Кофейня в Тюмени — 2ГИС"), encoding="utf-8"
    )
    (FIXTURES / "2gis_firm.html").write_text(
        as_2gis_page(build_2gis_card(search), "Ола Ола — 2ГИС"), encoding="utf-8"
    )
    yandex = build_yandex_search()
    (FIXTURES / "yandex_search.html").write_text(
        as_yandex_page(yandex, "Кофейня в Тюмени — Яндекс Карты"), encoding="utf-8"
    )
    card = dict(yandex["stack"][0]["results"]["items"][2])
    card["urls"] = ["https://prokofev-coffee.ru/"]
    card["socialLinks"] = [{"type": "vkontakte", "href": "https://vk.ru/prokofev",
                            "readableHref": "vk.ru/prokofev"}]
    (FIXTURES / "yandex_org.html").write_text(
        as_yandex_page({"stack": [{"results": {"items": [card], "totalResultCount": 1}}]},
                       "Прокофьев — Яндекс Карты"),
        encoding="utf-8",
    )
    for path in sorted(FIXTURES.glob("*.html")):
        print(f"  {path.name:<22} {path.stat().st_size // 1024} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
