"""Ниши: несколько запросов вместо одного слова.

Фирма сама решает, как себя назвать. Одна пишется «автосервисом», соседняя — «СТО»,
третья — «ремонтом автомобилей», и по одному слову две трети ниши в выдачу не попадут.
Поэтому ниша — это набор запросов: программа обходит их по очереди и складывает
найденное в один список, убирая повторы.

Ниши лежат в `mapsparser/templates/*.toml` и правятся обычным текстовым редактором:
это отправная точка, а не истина — под свой город и свой ассортимент словарь доводится.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"
MIN_PER_QUERY = 60  # меньше просто не имеет смысла: столько 2ГИС отдаёт за один запрос


@dataclass(frozen=True)
class Niche:
    """Готовый набор запросов под одну нишу."""

    name: str
    queries: tuple[str, ...]
    note: str = ""

    @property
    def title(self) -> str:
        return self.name

    def summary(self) -> str:
        return f"{self.name}: " + ", ".join(self.queries)


def _read(path: Path) -> Niche | None:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    name = str(raw.get("name", "")).strip()
    queries = tuple(str(q).strip() for q in raw.get("queries", []) if str(q).strip())
    if not name or not queries:
        return None
    return Niche(name=name, queries=queries, note=str(raw.get("note", "")).strip())


def load_niches() -> list[Niche]:
    """Все ниши из папки шаблонов, по алфавиту."""
    if not TEMPLATES_DIR.exists():
        return []
    found = [niche for path in sorted(TEMPLATES_DIR.glob("*.toml")) if (niche := _read(path))]
    return sorted(found, key=lambda niche: niche.name)


def find(name: str) -> Niche | None:
    """Ниша по названию. Регистр и «ё» не важны."""
    key = (name or "").strip().lower().replace("ё", "е")
    if not key:
        return None
    for niche in load_niches():
        if niche.name.lower().replace("ё", "е") == key:
            return niche
    return None


def names() -> list[str]:
    return [niche.name for niche in load_niches()]


def queries_for(query: str) -> tuple[str, ...]:
    """Запросы для введённого слова: набор ниши, если это ниша, иначе само слово."""
    niche = find(query)
    return niche.queries if niche else ((query.strip(),) if query.strip() else ())


def share(limit: int, count: int) -> int:
    """Сколько брать по каждому запросу, чтобы в сумме вышло примерно заказанное."""
    if count <= 1:
        return limit
    return max(MIN_PER_QUERY, limit // count)
