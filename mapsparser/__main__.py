"""Командная строка: всё, что умеет окно, доступно и из консоли.

    python -m mapsparser collect -q кофейня -c Тюмень
    python -m mapsparser collect -q автосервис -c Казань --gap website --limit 600
    python -m mapsparser cities Тюм
"""

from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
from pathlib import Path

from . import __version__
from .cache import Cache
from .cities import City, all_cities, find, suggest
from .excel import write_default
from .gaps import GAPS
from .http import Stopped
from .models import Place
from .niches import find as find_niche
from .niches import load_niches
from .normalize import pretty_phone
from .pipeline import Settings, run
from .settings import APP_TITLE, BRAND, default_cache_dir, default_output_dir
from .sources import all_sources, get, source_keys


def setup_console() -> None:
    """Консоль Windows по умолчанию живёт в cp1251 и падает на «—» и «₽»."""
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            with contextlib.suppress(ValueError, OSError):
                stream.reconfigure(encoding="utf-8", errors="replace")


def city_or_exit(name: str) -> City:
    city = find(name)
    if city:
        return city
    close = suggest(name, 6)
    hint = ", ".join(c.name for c in close)
    print(f"Город «{name}» в справочнике не нашёлся.", file=sys.stderr)
    if hint:
        print(f"Может быть, это: {hint}", file=sys.stderr)
    print("Полный список — команда «cities». Добавить город: tools/update_cities.py <название>", file=sys.stderr)
    raise SystemExit(2)


def cmd_collect(args: argparse.Namespace) -> int:
    city = city_or_exit(args.city)
    query, queries = _what_to_search(args)
    sources = [get(key) for key in args.source] if args.source else all_sources()
    settings = Settings(
        query=query,
        queries=queries,
        city=city,
        sources=sources,
        limit=args.limit,
        deep=not args.no_deep,
        delay=args.delay,
        use_cache=not args.no_cache,
        tiles=args.tiles,
        min_score=args.min_score,
        required_gaps=tuple(args.gap or ()),
        check_sites=not args.no_sites,
        site_limit=args.site_limit,
    )
    print(f"{APP_TITLE} by {BRAND} — ищу «{settings.query}» в городе {city.name}")
    try:
        result = run(settings, log=lambda message: print(" ", message))
    except Stopped:
        print("Остановлено.")
        return 1
    except KeyboardInterrupt:
        print("\nОстановлено.")
        return 1

    if not result.places:
        print("Ничего не нашлось. Попробуйте другое слово или снимите фильтры.")
        return 1

    _print_table(result.places[: args.show])
    directory = Path(args.out) if args.out else default_output_dir()
    report = write_default(result, directory)
    print(f"\nОтчёт: {report}")
    if args.csv:
        from .csvout import write as write_csv

        csv_path = write_csv(result, report.with_suffix(".csv"))
        print(f"CSV:    {csv_path}")
    if args.open:
        _open_file(report)
    return 0


def _print_table(places: list[Place]) -> None:
    print()
    print(f"{'Оц.':>4}  {'Фирма':<30} {'Телефон':<18} {'Чего нет'}")
    print("─" * 110)
    for place in places:
        phone = pretty_phone(place.phones[0]) if place.phones else "—"
        name = place.name if len(place.name) <= 30 else place.name[:29] + "…"
        gaps = ", ".join(place.gaps)
        print(f"{place.score:>4}  {name:<30} {phone:<18} {gaps[:50]}")


def _open_file(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(path)], check=False)
    except OSError as exc:
        print(f"Открыть файл не удалось: {exc}")


def _what_to_search(args: argparse.Namespace) -> tuple[str, tuple[str, ...]]:
    """Что искать: нишу целиком или одно слово."""
    if args.niche:
        niche = find_niche(args.niche)
        if not niche:
            known = ", ".join(n.name for n in load_niches())
            print(f"Ниша «{args.niche}» не нашлась. Есть: {known}", file=sys.stderr)
            raise SystemExit(2)
        return niche.name, niche.queries
    if not args.query:
        print("Укажите, кого ищем: --query «кофейня» или --niche «Автосервисы»", file=sys.stderr)
        raise SystemExit(2)
    return args.query, ()


def cmd_niches(_args: argparse.Namespace) -> int:
    found = load_niches()
    for niche in found:
        print(f"  {niche.name}")
        print(f"      {', '.join(niche.queries)}")
        if niche.note:
            print(f"      — {niche.note}")
    print()
    print(f"Всего ниш: {len(found)}. Свои правятся в mapsparser/templates/*.toml")
    return 0


def cmd_cities(args: argparse.Namespace) -> int:
    cities = suggest(args.prefix, 500) if args.prefix else all_cities()
    if not cities:
        print("Ничего не нашлось.")
        return 1
    for city in cities:
        print(f"  {city.name:<28} {city.alias:<24} {city.region}")
    print(f"\nВсего {len(cities)}. Нужного города нет — tools/update_cities.py <название>")
    return 0


def cmd_sources(_args: argparse.Namespace) -> int:
    for source in all_sources():
        print(f"  {source.key:<8} {source.title:<16} {source.site}")
        print(f"           {source.note}")
        print(f"           отдаёт: {', '.join(source.gives)}")
    return 0


def cmd_gaps(_args: argparse.Namespace) -> int:
    print(f"{'код':<12} {'вес':>4}  пробел")
    for gap in GAPS:
        print(f"{gap.code:<12} {gap.weight:>4}  {gap.title} — {gap.hint}")
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    cache = Cache(default_cache_dir())
    if args.clear:
        removed = cache.clear()
        print(f"Удалено страниц: {removed}")
        return 0
    print(f"Кэш: {cache.directory}")
    print(f"Занято: {cache.size_mb()} МБ")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mapsparser",
        description=f"{APP_TITLE} — организации города из 2ГИС и Яндекс Карт в Excel",
    )
    parser.add_argument("--version", action="version", version=f"{APP_TITLE} {__version__}")
    commands = parser.add_subparsers(dest="command")

    collect = commands.add_parser("collect", help="собрать организации и сделать отчёт")
    collect.add_argument("-q", "--query", help="что ищем: «кофейня», «автосервис»")
    collect.add_argument("-n", "--niche", help="готовая ниша: несколько запросов разом (список — команда niches)")
    collect.add_argument("-c", "--city", required=True, help="город: «Тюмень»")
    collect.add_argument(
        "-s", "--source", action="append", choices=source_keys(), help="только эта карта (можно повторять)"
    )
    collect.add_argument("-l", "--limit", type=int, default=300, help="сколько организаций брать с каждой карты")
    collect.add_argument("--no-deep", action="store_true", help="не открывать карточки 2ГИС (быстрее, но без почт)")
    collect.add_argument(
        "--no-sites", action="store_true", help="не заходить на сайты фирм (быстрее, но почт найдётся меньше)"
    )
    collect.add_argument("--site-limit", type=int, default=400, help="сколько сайтов проверять за сбор")
    collect.add_argument("--delay", type=float, default=1.5, help="пауза между запросами, секунды")
    collect.add_argument("--tiles", type=int, default=0, help="на сколько участков резать город в 2ГИС")
    collect.add_argument("--min-score", type=int, default=0, help="оставить фирмы с оценкой не ниже")
    collect.add_argument(
        "--gap", action="append", choices=[gap.code for gap in GAPS], help="оставить только с этим пробелом"
    )
    collect.add_argument("--no-cache", action="store_true", help="не использовать сохранённые страницы")
    collect.add_argument("--csv", action="store_true", help="сохранить ещё и CSV")
    collect.add_argument("--out", help="куда положить отчёт")
    collect.add_argument("--show", type=int, default=20, help="сколько строк показать в консоли")
    collect.add_argument("--open", action="store_true", help="открыть отчёт после сохранения")
    collect.set_defaults(func=cmd_collect)

    cities = commands.add_parser("cities", help="города, которые программа знает")
    cities.add_argument("prefix", nargs="?", default="", help="первые буквы названия")
    cities.set_defaults(func=cmd_cities)

    commands.add_parser("niches", help="готовые ниши и их запросы").set_defaults(func=cmd_niches)
    commands.add_parser("sources", help="какие карты подключены").set_defaults(func=cmd_sources)
    commands.add_parser("gaps", help="какие пробелы умеет находить").set_defaults(func=cmd_gaps)

    cache = commands.add_parser("cache", help="сохранённые страницы")
    cache.add_argument("--clear", action="store_true", help="очистить")
    cache.set_defaults(func=cmd_cache)
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
