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
from datetime import time
from pathlib import Path

from . import __version__, scheduler
from .cache import Cache
from .cities import City, all_cities, find, find_or_guess, suggest
from .excel import write_default
from .gaps import GAPS
from .history import Changes, History, run_key
from .history import summary as history_summary
from .http import Stopped
from .models import Place
from .monitor import Watch, add_watch, check_all, load_watchlist, remove_watch
from .niches import find as find_niche
from .niches import load_niches
from .normalize import pretty_phone
from .pipeline import Settings, run
from .settings import APP_TITLE, BRAND, default_cache_dir, default_output_dir
from .sources import all_sources, get, source_keys
from .telegram import Account, TelegramError, check_token, env_file, find_chat, load_account, save_account, send


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
    guessed = find_or_guess(name)
    if guessed:
        # Яндекс ищет по названию города, 2ГИС без короткого имени не умеет.
        print(f"Города «{name}» нет в справочнике: соберу только тем, кому короткое имя не нужно.")
        close = suggest(name, 5)
        if close:
            print("Если имелся в виду другой город: " + ", ".join(c.name for c in close))
        return guessed
    print("Укажите город: -c Тюмень", file=sys.stderr)
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
        skip_chains=args.no_chains,
        remember=not args.forget,
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

    if result.changes and not result.changes.first_run:
        _print_changes(result.changes)
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


def _print_changes(changes: Changes) -> None:
    """Новые фирмы — вперёд: в нише это самый горячий лид."""
    print()
    print(history_summary(changes))
    order = {"new": 0, "site_died": 1, "lost_site": 2, "gone": 3}
    for change in sorted(changes.items, key=lambda item: order.get(item.kind, 9))[:20]:
        print(f"  {change.text}")


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


def cmd_history(args: argparse.Namespace) -> int:
    folder = History("x").directory
    if not args.city or not args.query:
        files = sorted(folder.glob("*.json")) if folder.exists() else []
        for path in files:
            print(f"  {path.stem}")
        print()
        print(f"Сборов в памяти: {len(files)}. Папка: {folder}")
        return 0
    city = city_or_exit(args.city)
    history = History(run_key(city.alias or city.name, args.query))
    if args.forget:
        print("Забыто." if history.forget() else "Такого сбора в памяти нет.")
        return 0
    places, when = history.load()
    if not places:
        print("Такого сбора в памяти нет.")
        return 1
    print(f"Сбор от {when}: фирм {len(places)}")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    if args.what == "list" or not args.what:
        watches = load_watchlist()
        for watch in watches:
            extra = f", до {watch.limit} фирм" + ("" if watch.check_sites else ", без проверки сайтов")
            print(f"  {watch.title}{extra}")
        print(f"\nНиш под присмотром: {len(watches)}")
        if watches:
            print("Проверить сейчас — «monitor», по расписанию — «schedule on»")
        return 0
    if not args.city or not args.query:
        print("Нужны город и ниша: watch add -c Тюмень -q Автосервисы", file=sys.stderr)
        return 2
    city = city_or_exit(args.city)
    if args.what == "remove":
        print("Убрано." if remove_watch(city.name, args.query) else "Такой ниши в списке нет.")
        return 0
    watch = Watch(
        city=city.name,
        query=args.query,
        limit=args.limit,
        sources=tuple(args.source or ()),
        check_sites=not args.no_sites,
        skip_chains=args.no_chains,
    )
    add_watch(watch)
    print(f"Под присмотром: {watch.title}")
    print("Первая проверка запомнит нишу, со второй начнут приходить новые фирмы.")
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    results = check_all(log_message=lambda message: print(" ", message), notify=not args.no_notify)
    if not results:
        return 1
    print()
    for outcome in results:
        if outcome.error:
            print(f"  {outcome.watch.title}: {outcome.error}")
        else:
            print(f"  {outcome.watch.title}: фирм {outcome.found}, новых {outcome.new_count}, "
                  f"отправлено {outcome.sent}")
    return 0 if not any(outcome.error for outcome in results) else 1


def cmd_schedule(args: argparse.Namespace) -> int:
    try:
        if args.what == "on":
            at = _parse_time(args.at)
            scheduler.create(at, days=args.days)
            print(f"Проверки включены: каждые {args.days} сут. в {at:%H:%M}.")
            if not load_watchlist():
                print("Список наблюдений пуст — добавьте нишу: watch add -c Тюмень -q Автосервисы")
            return 0
        if args.what == "off":
            scheduler.disable()
            print("Проверки выключены. Настройки задания сохранены.")
            return 0
        if args.what == "remove":
            print("Задание удалено." if scheduler.remove() else "Задания и не было.")
            return 0
        state = scheduler.status()
        if not state.exists:
            print("Задание не создано. Включить — «schedule on».")
            return 0
        print(f"Задание: {'включено' if state.enabled else 'выключено'}")
        print(f"  следующий запуск: {state.next_run or '—'}")
        print(f"  прошлый запуск:   {state.last_run or '—'} ({state.last_result or '—'})")
        return 0
    except scheduler.SchedulerError as error:
        print(str(error), file=sys.stderr)
        return 1


def _parse_time(text: str) -> time:
    try:
        hours, _, minutes = text.partition(":")
        return time(int(hours), int(minutes or 0))
    except ValueError:
        print(f"Время «{text}» не разобрать, нужно вида 09:00", file=sys.stderr)
        raise SystemExit(2) from None


def cmd_telegram(args: argparse.Namespace) -> int:
    account = load_account()
    token = args.token or account.token
    chat = args.chat or account.chat
    try:
        if args.find_chat:
            if not token:
                print("Сначала задайте токен: telegram --token …", file=sys.stderr)
                return 2
            chat = find_chat(token)
            print(f"Ваш чат: {chat}")
        if args.token or args.chat or args.find_chat:
            name = check_token(token) if token else ""
            path = save_account(Account(token=token, chat=chat))
            print(f"Сохранено в {path}" + (f"; бот @{name}" if name else ""))
        if args.test:
            send(Account(token=token, chat=chat), "Карты Парсер на связи: проверка прошла.")
            print("Сообщение отправлено.")
        if not any((args.token, args.chat, args.find_chat, args.test)):
            ready = "настроен" if Account(token=token, chat=chat).ready else "не настроен"
            print(f"Telegram {ready}. Файл настроек: {env_file()}")
            print("Токен выдаёт @BotFather; номер чата подскажет «telegram --find-chat».")
        return 0
    except TelegramError as error:
        print(str(error), file=sys.stderr)
        return 1


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
    collect.add_argument("--no-chains", action="store_true", help="без сетевых точек: решает не филиал, а центр")
    collect.add_argument("--no-cache", action="store_true", help="не использовать сохранённые страницы")
    collect.add_argument("--forget", action="store_true", help="не помнить этот сбор (без разбора изменений)")
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

    watch = commands.add_parser("watch", help="ниши под присмотром")
    watch.add_argument("what", nargs="?", choices=["add", "remove", "list"], default="list")
    watch.add_argument("-c", "--city", help="город")
    watch.add_argument("-q", "--query", help="ниша или слово")
    watch.add_argument("-l", "--limit", type=int, default=300, help="сколько фирм собирать при проверке")
    watch.add_argument("-s", "--source", action="append", choices=source_keys(), help="только эта карта")
    watch.add_argument("--no-sites", action="store_true", help="не заходить на сайты фирм")
    watch.set_defaults(func=cmd_watch)

    monitor = commands.add_parser("monitor", help="проверить ниши и прислать новые фирмы в Telegram")
    monitor.add_argument("--no-notify", action="store_true", help="только посчитать, ничего не отправлять")
    monitor.set_defaults(func=cmd_monitor)

    schedule = commands.add_parser("schedule", help="проверки по расписанию")
    schedule.add_argument("what", nargs="?", choices=["on", "off", "status", "remove"], default="status")
    schedule.add_argument("--at", default="09:00", help="во сколько проверять, например 09:00")
    schedule.add_argument("--days", type=int, default=1, help="раз во сколько суток")
    schedule.set_defaults(func=cmd_schedule)

    telegram = commands.add_parser("telegram", help="бот и чат для уведомлений")
    telegram.add_argument("--token", help="токен бота от @BotFather")
    telegram.add_argument("--chat", help="номер чата")
    telegram.add_argument("--find-chat", action="store_true", help="найти номер чата по сообщению боту")
    telegram.add_argument("--test", action="store_true", help="отправить проверочное сообщение")
    telegram.set_defaults(func=cmd_telegram)

    history = commands.add_parser("history", help="память о прошлых сборах")
    history.add_argument("-c", "--city", help="город сбора")
    history.add_argument("-q", "--query", help="ниша или слово")
    history.add_argument("--forget", action="store_true", help="забыть этот сбор")
    history.set_defaults(func=cmd_history)
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
