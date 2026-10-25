"""Мониторинг ниш: раз в сутки собрать и прислать только новые фирмы.

Разовая выгрузка — это снимок. Подписка «новые фирмы твоей ниши» — товар:
у новой точки ещё нет ни сайта, ни отзывов, и прямо сейчас кто-то решает,
где всё это заказывать. Поэтому мониторинг шлёт не весь список, а разницу
с прошлой проверкой — её считает `history`.

Наблюдения (город плюс ниша) лежат рядом с настройками программы, проверка
запускается командой `monitor` — её же дёргает задание Планировщика Windows.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .cities import City
from .cities import find as find_city
from .history import Changes
from .pipeline import Settings, run
from .settings import user_data_dir
from .sources import all_sources, resolve
from .telegram import Account, TelegramError, load_account, new_places_message, send

log = logging.getLogger(__name__)

MAX_CARDS_PER_MESSAGE = 15  # больше в одно сообщение не влезает, да и читать невозможно


@dataclass(frozen=True)
class Watch:
    """Одна ниша под присмотром."""

    city: str
    query: str
    limit: int = 300
    sources: tuple[str, ...] = ()
    deep: bool = True
    check_sites: bool = True

    @property
    def title(self) -> str:
        return f"{self.query} — {self.city}"

    def key(self) -> str:
        return f"{self.city.lower()}|{self.query.lower()}"


def watchlist_file() -> Path:
    return user_data_dir() / "watchlist.json"


def load_watchlist() -> list[Watch]:
    path = watchlist_file()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    found: list[Watch] = []
    for item in raw.get("watches", []):
        if item.get("city") and item.get("query"):
            found.append(
                Watch(
                    city=str(item["city"]),
                    query=str(item["query"]),
                    limit=int(item.get("limit", 300)),
                    sources=tuple(item.get("sources", ())),
                    deep=bool(item.get("deep", True)),
                    check_sites=bool(item.get("check_sites", True)),
                )
            )
    return found


def save_watchlist(watches: list[Watch]) -> Path:
    path = watchlist_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"watches": [asdict(watch) for watch in watches]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def add_watch(watch: Watch) -> list[Watch]:
    watches = [item for item in load_watchlist() if item.key() != watch.key()]
    watches.append(watch)
    save_watchlist(watches)
    return watches


def remove_watch(city: str, query: str) -> bool:
    watches = load_watchlist()
    kept = [item for item in watches if item.key() != Watch(city=city, query=query).key()]
    if len(kept) == len(watches):
        return False
    save_watchlist(kept)
    return True


@dataclass
class CheckResult:
    """Что дала одна проверка одной ниши."""

    watch: Watch
    found: int = 0
    changes: Changes | None = None
    sent: int = 0
    error: str = ""

    @property
    def new_count(self) -> int:
        return len(self.changes.new) if self.changes else 0


def check(
    watch: Watch,
    *,
    account: Account | None = None,
    log_message: Callable[[str], None] | None = None,
    notify: bool = True,
    city: City | None = None,
) -> CheckResult:
    """Собирает нишу и отправляет в Telegram только то, чего не было в прошлый раз."""
    say = log_message or (lambda _message: None)
    found_city = city or find_city(watch.city)
    if not found_city:
        return CheckResult(watch=watch, error=f"город «{watch.city}» не нашёлся")

    settings = Settings(
        query=watch.query,
        city=found_city,
        sources=resolve(list(watch.sources)) if watch.sources else all_sources(),
        limit=watch.limit,
        deep=watch.deep,
        check_sites=watch.check_sites,
        remember=True,
    )
    say(f"Проверяю: {watch.title}")
    result = run(settings, log=say)
    outcome = CheckResult(watch=watch, found=len(result.places), changes=result.changes)

    if result.changes.first_run:
        say("Первая проверка этой ниши — запомнил, в следующий раз пришлю новые.")
        return outcome
    new_places = [change.place for change in result.changes.new if change.place]
    if not new_places:
        say("Новых фирм нет.")
        return outcome

    say(f"Новых фирм: {len(new_places)}")
    if not notify:
        return outcome
    account = account or load_account()
    if not account.ready:
        outcome.error = "не настроен Telegram: нет токена бота или номера чата"
        say(outcome.error)
        return outcome
    try:
        for start in range(0, len(new_places), MAX_CARDS_PER_MESSAGE):
            part = new_places[start : start + MAX_CARDS_PER_MESSAGE]
            send(account, new_places_message(found_city.name, watch.query, part))
            outcome.sent += len(part)
    except TelegramError as error:
        outcome.error = str(error)
        say(f"Телеграм не принял сообщение: {error}")
    return outcome


def check_all(
    *,
    log_message: Callable[[str], None] | None = None,
    notify: bool = True,
) -> list[CheckResult]:
    """Проверяет все наблюдения по очереди. Беда с одним не мешает остальным."""
    say = log_message or (lambda _message: None)
    watches = load_watchlist()
    if not watches:
        say("Список наблюдений пуст: добавьте нишу командой «watch add».")
        return []
    say(f"Наблюдений: {len(watches)}; проверка начата {datetime.now().astimezone():%d.%m.%Y %H:%M}")
    results = []
    for watch in watches:
        try:
            results.append(check(watch, log_message=say, notify=notify))
        except Exception as error:
            log.exception("Проверка %s не удалась", watch.title)
            results.append(CheckResult(watch=watch, error=str(error)))
    return results
