"""История сборов: что в нише изменилось с прошлого раза."""

from __future__ import annotations

from pathlib import Path

import pytest

from mapsparser.history import History, compare, place_key, run_key, summary
from mapsparser.models import EMAIL, PHONE, WEBSITE, Company, Link, Place, SiteReport


def place(
    name: str = "Ола Ола",
    address: str = "Профсоюзная улица, 56",
    *,
    links: tuple[Link, ...] = (),
    rating: float | None = 4.8,
    reviews: int = 125,
    site: SiteReport | None = None,
) -> Place:
    company = Company(
        source="2gis", source_id="1", name=name, address=address,
        lat=57.15, lon=65.55, rating=rating, reviews=reviews, links=links,
    )
    return Place(name=name, address=address, city="Тюмень", lat=57.15, lon=65.55,
                 by_source={"2gis": company}, site=site)


def saved(tmp_path: Path, places: list[Place]) -> History:
    history = History("tyumen-кофейня", tmp_path)
    history.save(places)
    return history


def test_place_key_survives_a_different_spelling() -> None:
    """Фирма опознаётся по названию и месту: карта может сменить номер карточки."""
    assert place_key(place("Ола Ола, кофейня", "Профсоюзная ул., 56")) == place_key(
        place("Ола Ола", "улица Профсоюзная, 56")
    )


def test_place_key_separates_branches() -> None:
    assert place_key(place(address="улица Ленина, 57")) != place_key(place(address="улица Ленина, 59"))


def test_run_key_is_made_of_city_and_niche() -> None:
    assert run_key("tyumen", "кофейня") == "tyumen-кофейня"
    assert run_key("tyumen", "Кафе и кофейни") == "tyumen-кафе_и_кофейни"
    assert run_key("tyumen", "") == "tyumen"


def test_first_run_has_nothing_to_compare(tmp_path: Path) -> None:
    history = History("tyumen-кофейня", tmp_path)
    previous, when = history.load()
    changes = compare([place()], previous, when)
    assert changes.first_run is True
    assert not changes.items
    assert "первый сбор" in summary(changes)


def test_a_new_firm_is_the_main_find(tmp_path: Path) -> None:
    history = saved(tmp_path, [place()])
    previous, when = history.load()
    changes = compare([place(), place("Кофе и Точка", "улица Ленина, 57А")], previous, when)
    assert [change.name for change in changes.new] == ["Кофе и Точка"]
    assert "новых: 1" in summary(changes)


def test_a_firm_that_vanished_is_noticed(tmp_path: Path) -> None:
    history = saved(tmp_path, [place(), place("Кофе и Точка", "улица Ленина, 57А")])
    previous, when = history.load()
    changes = compare([place()], previous, when)
    assert [change.name for change in changes.of("gone")] == ["Кофе и Точка"]


def test_a_site_appearing_is_a_change(tmp_path: Path) -> None:
    history = saved(tmp_path, [place()])
    previous, when = history.load()
    changes = compare([place(links=(Link(WEBSITE, "https://ola-ola.ru"),))], previous, when)
    assert changes.of("got_site")
    assert changes.of("got_site")[0].now == "https://ola-ola.ru"


def test_a_site_that_died_is_a_change(tmp_path: Path) -> None:
    alive = SiteReport(url="https://ola-ola.ru", reachable=True)
    dead = SiteReport(url="https://ola-ola.ru", reachable=False, error="Timeout")
    history = saved(tmp_path, [place(site=alive)])
    previous, when = history.load()
    changes = compare([place(site=dead)], previous, when)
    assert changes.of("site_died")
    assert "сайт умер: 1" in summary(changes)


def test_email_appearing_and_phone_vanishing(tmp_path: Path) -> None:
    before = place(links=(Link(PHONE, "+73452666707"),))
    after = place(links=(Link(EMAIL, "ola@mail.ru"),))
    history = saved(tmp_path, [before])
    previous, when = history.load()
    changes = compare([after], previous, when)
    assert changes.of("got_email")
    assert changes.of("lost_phone")


@pytest.mark.parametrize(
    ("was", "now", "kind"),
    [(4.8, 4.2, "rating_down"), (4.2, 4.8, "rating_up"), (4.8, 4.7, "")],
)
def test_rating_moves_only_when_it_really_moved(tmp_path: Path, was: float, now: float, kind: str) -> None:
    history = saved(tmp_path, [place(rating=was)])
    previous, when = history.load()
    changes = compare([place(rating=now)], previous, when)
    kinds = {change.kind for change in changes.items}
    assert (kind in kinds) if kind else not kinds  # 0.1 — это шум, а не изменение


def test_reviews_jump_is_noticed(tmp_path: Path) -> None:
    history = saved(tmp_path, [place(reviews=100)])
    previous, when = history.load()
    assert compare([place(reviews=125)], previous, when).of("reviews_jump")
    history = saved(tmp_path, [place(reviews=100)])
    previous, when = history.load()
    assert not compare([place(reviews=103)], previous, when).of("reviews_jump")


def test_first_seen_is_kept_between_runs(tmp_path: Path) -> None:
    history = saved(tmp_path, [place()])
    previous, _ = history.load()
    first = previous[place_key(place())].first_seen
    history.save([place()], previous=previous)
    again, _ = history.load()
    assert again[place_key(place())].first_seen == first


def test_history_can_be_forgotten(tmp_path: Path) -> None:
    history = saved(tmp_path, [place()])
    assert history.path.exists()
    assert history.forget() is True
    assert history.forget() is False


def test_broken_history_file_does_not_break_the_run(tmp_path: Path) -> None:
    history = History("tyumen-кофейня", tmp_path)
    history.path.parent.mkdir(parents=True, exist_ok=True)
    history.path.write_text("{это не json", encoding="utf-8")
    previous, when = history.load()
    assert previous == {}
    assert when == ""


def test_changes_text_reads_like_a_sentence(tmp_path: Path) -> None:
    history = saved(tmp_path, [place(rating=4.8)])
    previous, when = history.load()
    changes = compare([place(rating=4.2)], previous, when)
    assert changes.items[0].text == "Ола Ола: рейтинг просел (4.8 → 4.2)"
