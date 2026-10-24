r"""Собирает пример отчёта для README — docs/example/example-report.xlsx.

Фирмы берутся из сохранённых страниц (tests/fixtures), поэтому пример не зависит
от сети и не содержит ничьих настоящих контактов.

    .venv\Scripts\python tools\make_example.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from demo_data import demo_result

from mapsparser.csvout import write as write_csv
from mapsparser.excel import write as write_excel


def main() -> int:
    result = demo_result()
    folder = ROOT / "docs" / "example"
    folder.mkdir(parents=True, exist_ok=True)
    book = write_excel(result, folder / "example-report.xlsx")
    table = write_csv(result, folder / "example-report.csv")
    print(f"Фирм в примере: {len(result.places)}")
    print(f"  {book}")
    print(f"  {table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
