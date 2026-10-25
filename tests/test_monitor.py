"""Мониторинг ниш, сообщения в Telegram и задание Планировщика.

Ни один тест не ходит в сеть и не трогает Планировщик: отправка подменяется,
schtasks — поддельным запуском, который запоминает аргументы.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, time
from pathlib import Path

import pytest

from mapsparser import monitor as monitor_module
from mapsparser import scheduler, telegram
from mapsparser.models import EMAIL, PHONE, Company, Link, Place
from mapsparser.monitor import Watch, add_watch, check, check_all, load_watchlist, remove_watch
from mapsparser.telegram import Account, SecretFilter, TelegramError, card, new_places_message

TOKEN = "123456789:AAEtestTokenThatLooksRealEnough1234567"


@pytest.fixture(autouse=True)
def own_folder(tmp_path: Path, monkeypatch) -> Path:
    """Наблюдения и .env пишем в свою папку, а не в настройки пользователя."""
    monkeypatch.setattr(monitor_module, "watchlist_file", lambda: tmp_path / "watchlist.json")
    monkeypatch.setattr(telegram, "env_file", lambda: tmp_path / ".env")
    return tmp_path


def place(name: str = "Ола Ола") -> Place:
    company = Company(
        source="2gis", source_id="1", name=name, url="https://2gis.ru/tyumen/firm/1",
        address="Профсоюзная улица, 56", rubrics=("Кофейни",),
        links=(Link(PHONE, "+73452666707"), Link(EMAIL, "ola@mail.ru")),
    )
    spot = Place(name=name, address="Профсоюзная улица, 56", city="Тюмень", by_source={"2gis": company})
    spot.gaps = ("нет сайта",)
    return spot


# ------------------------------------------------------------------ список наблюдений


def test_watchlist_survives_a_restart() -> None:
    add_watch(Watch(city="Тюмень", query="Автосервисы"))
    assert [watch.title for watch in load_watchlist()] == ["Автосервисы — Тюмень"]


def test_adding_the_same_niche_twice_does_not_double_it() -> None:
    add_watch(Watch(city="Тюмень", query="Автосервисы"))
    add_watch(Watch(city="Тюмень", query="автосервисы", limit=500))
    watches = load_watchlist()
    assert len(watches) == 1
    assert watches[0].limit == 500  # запомнились новые настройки


def test_a_niche_can_be_removed() -> None:
    add_watch(Watch(city="Тюмень", query="Автосервисы"))
    assert remove_watch("Тюмень", "Автосервисы") is True
    assert remove_watch("Тюмень", "Автосервисы") is False
    assert load_watchlist() == []


def test_broken_watchlist_file_does_not_break_the_check(own_folder: Path) -> None:
    (own_folder / "watchlist.json").write_text("{это не json", encoding="utf-8")
    assert load_watchlist() == []


# ------------------------------------------------------------------ проверка ниши


def test_first_check_only_remembers(monkeypatch, tyumen) -> None:
    """Первая проверка сравнивать не с чем — рассылать нечего."""
    from mapsparser.history import Changes
    from mapsparser.pipeline import Result, Settings

    def fake_run(settings: Settings, **_kwargs: object) -> Result:
        return Result(settings=settings, places=[place()], changes=Changes(first_run=True))

    monkeypatch.setattr(monitor_module, "run", fake_run)
    sent: list[str] = []
    monkeypatch.setattr(monitor_module, "send", lambda account, text, **kw: sent.append(text))
    outcome = check(Watch(city="Тюмень", query="кофейня"), account=Account(TOKEN, "1"), city=tyumen)
    assert outcome.new_count == 0
    assert outcome.sent == 0
    assert sent == []


def test_new_firms_are_sent_to_telegram(monkeypatch, tyumen) -> None:
    from mapsparser.history import Change, Changes
    from mapsparser.pipeline import Result, Settings

    new = place("Кофе и Точка")
    changes = Changes(items=[Change("new", "новая фирма в нише", new, name=new.name)])

    def fake_run(settings: Settings, **_kwargs: object) -> Result:
        return Result(settings=settings, places=[place(), new], changes=changes)

    monkeypatch.setattr(monitor_module, "run", fake_run)
    sent: list[str] = []
    monkeypatch.setattr(monitor_module, "send", lambda account, text, **kw: sent.append(text))
    outcome = check(Watch(city="Тюмень", query="кофейня"), account=Account(TOKEN, "1"), city=tyumen)
    assert outcome.new_count == 1
    assert outcome.sent == 1
    assert "Кофе и Точка" in sent[0]
    assert "Ола Ола" not in sent[0]  # шлём только новое, а не весь список


def test_telegram_trouble_does_not_lose_the_result(monkeypatch, tyumen) -> None:
    from mapsparser.history import Change, Changes
    from mapsparser.pipeline import Result

    new = place("Кофе и Точка")
    changes = Changes(items=[Change("new", "новая фирма в нише", new, name=new.name)])
    monkeypatch.setattr(
        monitor_module, "run", lambda settings, **_k: Result(settings=settings, places=[new], changes=changes)
    )

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise TelegramError("Unauthorized")

    monkeypatch.setattr(monitor_module, "send", refuse)
    outcome = check(Watch(city="Тюмень", query="кофейня"), account=Account(TOKEN, "1"), city=tyumen)
    assert outcome.new_count == 1
    assert outcome.sent == 0
    assert "Unauthorized" in outcome.error


def test_unknown_city_is_reported_not_raised() -> None:
    outcome = check(Watch(city="Город-которого-нет", query="кофейня"), notify=False)
    assert "не нашёлся" in outcome.error


def test_one_broken_niche_does_not_stop_the_others(monkeypatch) -> None:
    add_watch(Watch(city="Город-которого-нет", query="кофейня"))
    add_watch(Watch(city="Тюмень", query="кофейня"))
    monkeypatch.setattr(
        monitor_module, "check",
        lambda watch, **kw: monitor_module.CheckResult(watch=watch, found=1),
    )
    results = check_all(notify=False)
    assert len(results) == 2


# ------------------------------------------------------------------ сообщения


def test_card_shows_contacts_and_gaps() -> None:
    text = card(place())
    assert "Ола Ола" in text
    assert "+7 (345) 266-67-07" in text
    assert "ola@mail.ru" in text
    assert "нет сайта" in text
    assert "2gis.ru/tyumen/firm/1" in text


def test_card_escapes_dangerous_characters() -> None:
    assert "&lt;" in card(place("<b>Жирный</b>"))


def test_message_names_the_niche_and_the_city() -> None:
    text = new_places_message("Тюмень", "Автосервисы", [place()])
    assert "Автосервисы" in text
    assert "Тюмень" in text
    assert "Нашлось: 1" in text


def test_long_message_is_split() -> None:
    parts = telegram._split("строка\n" * 2000)
    assert len(parts) > 1
    assert all(len(part) <= telegram.MAX_MESSAGE for part in parts)


def test_token_never_reaches_the_log() -> None:
    record = type("R", (), {"msg": f"ошибка с токеном {TOKEN}"})()
    SecretFilter().filter(record)
    assert TOKEN not in record.msg
    assert "токен скрыт" in record.msg


def test_rubbish_instead_of_a_token_is_explained() -> None:
    with pytest.raises(TelegramError, match="не похоже на токен"):
        telegram._call("просто слова", "getMe")


def test_account_is_saved_and_loaded() -> None:
    telegram.save_account(Account(token=TOKEN, chat="12345"))
    account = telegram.load_account()
    assert account.token == TOKEN
    assert account.chat == "12345"
    assert account.ready is True


def test_sending_without_settings_is_refused() -> None:
    with pytest.raises(TelegramError, match="токен"):
        telegram.send(Account(), "привет")


# ------------------------------------------------------------------ расписание


def test_task_xml_describes_what_matters() -> None:
    xml = scheduler.task_xml(
        time(9, 0), days=1, now=datetime(2026, 10, 25, 12, 0),
        program=(Path("C:/app/MapsParser.exe"), [], Path("C:/app")),
    )
    assert "<StartBoundary>2026-10-25T09:00:00</StartBoundary>" in xml
    assert "<DaysInterval>1</DaysInterval>" in xml
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml  # догонит пропущенный запуск
    assert "monitor" in xml
    assert "MapsParser.exe" in xml  # Windows пишет путь со своими косыми


def test_creating_the_task_passes_xml_to_schtasks() -> None:
    calls: list[list[str]] = []

    def runner(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    scheduler.create(time(9, 0), runner=runner)
    assert calls[0][:2] == ["schtasks", "/Create"]
    assert "/XML" in calls[0]
    assert scheduler.TASK_PATH in calls[0]


def test_a_refusal_of_schtasks_is_explained() -> None:
    def runner(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(arguments, 1, "", "Отказано в доступе")

    with pytest.raises(scheduler.SchedulerError, match="Отказано"):
        scheduler.create(time(9, 0), runner=runner)


def test_status_of_a_missing_task() -> None:
    def runner(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(arguments, 1, "", "не найдено")

    assert scheduler.status(runner=runner).exists is False


def test_status_reads_the_task_listing() -> None:
    listing = (
        "Имя задачи: \\Maps Parser\\Мониторинг\n"
        "Состояние: Готово\n"
        "Время следующего запуска: 26.10.2026 9:00:00\n"
        "Время прошлого запуска: 25.10.2026 9:00:00\n"
        "Код последнего запуска: 0\n"
    )

    def runner(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(arguments, 0, listing, "")

    state = scheduler.status(runner=runner)
    assert state.exists and state.enabled
    assert state.next_run.startswith("26.10.2026")
    assert state.last_result == "0"


def test_a_disabled_task_is_seen_as_disabled() -> None:
    def runner(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(arguments, 0, "Состояние: Отключено\n", "")

    assert scheduler.status(runner=runner).enabled is False
