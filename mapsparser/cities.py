"""Города: как город называется в адресе 2ГИС и как его искать.

Яндексу хватает названия города в тексте запроса. 2ГИС просит короткое имя в адресе —
`2gis.ru/tyumen/...` — и на незнакомое отвечает 404. Поэтому здесь лежит справочник
проверенных имён, правила перевода названия в латиницу для городов не из справочника
и память о том, что однажды уже удалось найти.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .settings import user_data_dir

DATA_FILE = Path(__file__).parent / "data" / "cities.json"


@dataclass(frozen=True)
class City:
    """Город в понятиях источников."""

    name: str  # «Тюмень» — так его пишет пользователь и так ищет Яндекс
    alias: str  # «tyumen» — так его зовёт 2ГИС в адресе страницы
    region: str = ""  # «Тюменская область» — чтобы отличить одноимённые города
    region_id: str = ""  # идентификатор региона в 2ГИС

    @property
    def title(self) -> str:
        return f"{self.name} ({self.region})" if self.region else self.name


# Буква за буквой: так 2ГИС переводит названия в латиницу.
_LETTERS = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "-": "_", " ": "_",
}


def transliterate(text: str) -> str:
    """«Нижний Новгород» → «nizhniy_novgorod»."""
    return "".join(_LETTERS.get(ch, ch) for ch in (text or "").lower().strip())


def alias_candidates(name: str) -> list[str]:
    """Варианты короткого имени для 2ГИС, от самого вероятного к менее."""
    base = transliterate(name)
    variants = [base, base.replace("_", ""), base.replace("_", "-")]
    if base.startswith("nizhniy_"):
        variants.insert(0, "n_" + base.removeprefix("nizhniy_"))
    if base.startswith("velikiy_"):
        variants.insert(0, "v_" + base.removeprefix("velikiy_"))
    # «y» на конце слова 2ГИС иногда опускает: «yuzhno_sahalinsk», а не «yuzhno_sahalinskiy».
    if base.endswith("iy"):
        variants.append(base[:-2])
    seen: dict[str, None] = {}
    for variant in variants:
        if variant:
            seen.setdefault(variant, None)
    return list(seen)


def _normalise(name: str) -> str:
    return (name or "").strip().lower().replace("ё", "е")


def load_catalogue() -> dict[str, City]:
    """Справочник городов из файла пакета плюс города, найденные на этом компьютере."""
    cities: dict[str, City] = {}
    for path in (DATA_FILE, learned_file()):
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in raw.get("cities", []):
            city = City(
                name=item.get("name", ""),
                alias=item.get("alias", ""),
                region=item.get("region", ""),
                region_id=str(item.get("region_id", "")),
            )
            if city.name and city.alias:
                cities[_normalise(city.name)] = city
    return cities


def learned_file() -> Path:
    """Города, которые программа нашла сама — чтобы второй раз не искать."""
    return user_data_dir() / "cities-found.json"


def remember(city: City) -> None:
    """Запоминает найденный город рядом с настройками пользователя."""
    path = learned_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    known: dict[str, dict[str, str]] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            known = {_normalise(c["name"]): c for c in raw.get("cities", [])}
        except (OSError, json.JSONDecodeError, KeyError):
            known = {}
    known[_normalise(city.name)] = {
        "name": city.name,
        "alias": city.alias,
        "region": city.region,
        "region_id": city.region_id,
    }
    payload = {"cities": sorted(known.values(), key=lambda c: c["name"])}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def find(name: str) -> City | None:
    """Город из справочника по названию. Регистр и «ё» не важны."""
    if not name:
        return None
    catalogue = load_catalogue()
    key = _normalise(name)
    if key in catalogue:
        return catalogue[key]
    # «г. Тюмень», «Тюмень, Тюменская область»
    stripped = key.removeprefix("г.").removeprefix("г ").split(",")[0].strip()
    return catalogue.get(stripped)


def suggest(prefix: str, limit: int = 12) -> list[City]:
    """Города, начинающиеся с введённых букв — для подсказки в окне."""
    key = _normalise(prefix)
    cities = sorted(load_catalogue().values(), key=lambda c: c.name)
    if not key:
        return cities[:limit]
    starts = [c for c in cities if _normalise(c.name).startswith(key)]
    contains = [c for c in cities if key in _normalise(c.name) and c not in starts]
    return (starts + contains)[:limit]


def all_cities() -> list[City]:
    return sorted(load_catalogue().values(), key=lambda c: c.name)
