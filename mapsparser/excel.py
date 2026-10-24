"""Отчёт в Excel.

Два листа. «Фирмы» — то, ради чего всё затевалось: строка на фирму, контакты из обеих
карт и колонка «чего нет». «Сводка» — честный разбор сбора: сколько нашлось, сколько
запросов, где источник упёрся в свой потолок и каких пробелов сколько.

Оформление — фирменное: тёмная шапка, зелёный акцент, моноширинный шрифт у контактов.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from . import __version__
from .gaps import GAPS, hints_for
from .models import LINK_TITLES, Place
from .normalize import pretty_phone
from .pipeline import Result
from .settings import APP_TITLE, BRAND

# Фирменные цвета krein: тёмный фон, зелёный акцент, приглушённый текст.
INK = "0A0C0F"
PAPER = "F4F3EE"
ACCENT = "5CF28E"
ACCENT_DARK = "0C9A4A"
MUTED = "7C8692"
LINE = "D2CEC3"
WARM = "FFF4D6"  # подсветка строк с самой высокой оценкой

HEADER_FONT = Font(name="JetBrains Mono", size=10, bold=True, color=PAPER)
HEADER_FILL = PatternFill("solid", fgColor=INK)
TEXT_FONT = Font(name="Calibri", size=11)
MONO_FONT = Font(name="Consolas", size=10)
LINK_FONT = Font(name="Calibri", size=11, color="0C5BA8", underline="single")
MUTED_FONT = Font(name="Calibri", size=11, color=MUTED)
TITLE_FONT = Font(name="JetBrains Mono", size=14, bold=True, color=INK)
THIN = Side(style="thin", color=LINE)
CELL_BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


class Column:
    """Колонка листа «Фирмы»: заголовок, ширина и как достать значение."""

    def __init__(self, title: str, width: int, getter, *, mono: bool = False, wrap: bool = False) -> None:
        self.title = title
        self.width = width
        self.getter = getter
        self.mono = mono
        self.wrap = wrap


def _phones(place: Place) -> str:
    return "\n".join(pretty_phone(value) for value in place.phones)


def _socials(place: Place) -> str:
    return "\n".join(f"{LINK_TITLES.get(link.kind, link.kind)}: {link.value}" for link in place.socials)


def _sources(place: Place, result: Result) -> str:
    titles = {source.key: source.title for source in result.settings.sources}
    return ", ".join(titles.get(key, key) for key in sorted(place.by_source))


def columns(result: Result) -> list[Column]:
    """Набор колонок. Ссылки на карточки — по колонке на каждый источник из набора."""
    base: list[Column] = [
        Column("Фирма", 34, lambda p: p.name, wrap=True),
        Column("Чего нет", 38, lambda p: ", ".join(p.gaps), wrap=True),
        Column("Оценка", 8, lambda p: p.score),
        Column("Чем заняться", 34, lambda p: "; ".join(hints_for(p.gaps)), wrap=True),
        Column("Рубрика", 22, lambda p: ", ".join(p.rubrics[:3]), wrap=True),
        Column("Адрес", 32, lambda p: p.address, wrap=True),
        Column("Телефон", 19, _phones, mono=True),
        Column("Почта", 26, lambda p: "\n".join(p.emails), mono=True),
        Column("Сайт", 30, lambda p: "\n".join(p.websites), mono=True),
        Column("Соцсети и мессенджеры", 34, _socials, mono=True, wrap=True),
        Column("Рейтинг", 9, lambda p: p.rating),
        Column("Оценок", 9, lambda p: p.reviews or None),
        Column("Режим работы", 28, lambda p: p.schedule, wrap=True),
        Column("Источники", 18, lambda p: _sources(p, result)),
    ]
    for source in result.settings.sources:
        base.append(Column(f"Ссылка · {source.title}", 16, _link_getter(source.key)))
    base.append(Column("Координаты", 20, lambda p: f"{p.lat}, {p.lon}" if p.lat and p.lon else "", mono=True))
    return base


def _link_getter(key: str):
    def getter(place: Place) -> str:
        return place.url(key)

    return getter


def write(result: Result, path: Path) -> Path:
    """Собирает книгу и сохраняет её. Возвращает путь к файлу."""
    workbook = Workbook()
    firms = workbook.active
    firms.title = "Фирмы"
    _fill_firms(firms, result)
    _fill_summary(workbook.create_sheet("Сводка"), result)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path


def _fill_firms(sheet: Worksheet, result: Result) -> None:
    cols = columns(result)
    for index, column in enumerate(cols, 1):
        cell = sheet.cell(row=1, column=index, value=column.title)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        sheet.column_dimensions[get_column_letter(index)].width = column.width
    sheet.row_dimensions[1].height = 30

    link_titles = {f"Ссылка · {source.title}" for source in result.settings.sources}
    for row, place in enumerate(result.places, start=2):
        for index, column in enumerate(cols, 1):
            value = column.getter(place)
            cell = sheet.cell(row=row, column=index, value=value if value not in ("", None) else None)
            cell.font = MONO_FONT if column.mono else TEXT_FONT
            cell.alignment = Alignment(vertical="top", wrap_text=column.wrap)
            cell.border = CELL_BORDER
            if column.title in link_titles and value:
                cell.value = "открыть"
                cell.hyperlink = value
                cell.font = LINK_FONT
            elif column.title == "Чем заняться":
                cell.font = MUTED_FONT
        sheet.row_dimensions[row].height = None

    last_row = max(2, len(result.places) + 1)
    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{last_row}"

    score_column = get_column_letter(next(i for i, c in enumerate(cols, 1) if c.title == "Оценка"))
    sheet.conditional_formatting.add(
        f"{score_column}2:{score_column}{last_row}",
        ColorScaleRule(
            start_type="num", start_value=0, start_color=PAPER,
            mid_type="num", mid_value=40, mid_color="D8F5E3",
            end_type="num", end_value=80, end_color=ACCENT,
        ),
    )


def _fill_summary(sheet: Worksheet, result: Result) -> None:
    settings = result.settings
    sheet.column_dimensions["A"].width = 38
    sheet.column_dimensions["B"].width = 58

    title = sheet.cell(row=1, column=1, value=f"{APP_TITLE} by {BRAND}")
    title.font = TITLE_FONT
    sheet.cell(row=2, column=1, value=f"версия {__version__}").font = MUTED_FONT

    rows: list[tuple[str, object]] = [
        ("", ""),
        ("Что искали", settings.query or "все организации"),
        ("Город", settings.city.title),
        ("Когда собрано", (result.finished_at or datetime.now().astimezone()).strftime("%d.%m.%Y %H:%M")),
        ("Карты", ", ".join(source.title for source in settings.sources)),
        ("", ""),
        ("Фирм в отчёте", len(result.places)),
        ("Из них есть в обеих картах", result.in_both),
        ("Карточек собрано всего", result.collected),
        ("Запросов к картам", result.requests),
        ("Времени на сбор", f"{result.seconds:.0f} с"),
    ]
    for source in settings.sources:
        report = result.reports.get(source.key)
        if not report:
            continue
        note = "показал всё, что есть" if report.exhaustive else "упёрся в заданное число фирм"
        if report.capped:
            note = "упёрся в собственный потолок выдачи"
        rows.append((f"{source.title}: найдено", f"{len(report.companies)} — {note}"))

    counter = Counter(title for place in result.places for title in place.gaps)
    rows += [("", ""), ("Чего фирмам не хватает", "сколько фирм")]
    for gap in GAPS:
        if counter.get(gap.title):
            rows.append((gap.title, counter[gap.title]))

    rows += [
        ("", ""),
        ("Как читать «Оценка»", "0–100: чем больше пробелов, тем выше. 0 — либо всё на месте, либо связаться не с кем"),
        ("Откуда данные", "открытые страницы 2ГИС и Яндекс Карт, без ключей и регистрации"),
        ("О чём помнить", "карты показывают не всё: у 2ГИС выдача ограничена, у Яндекса — листание"),
    ]

    for index, (name, value) in enumerate(rows, start=4):
        label = sheet.cell(row=index, column=1, value=name or None)
        label.font = Font(name="Calibri", size=11, bold=not str(value).isdigit() and bool(name))
        label.alignment = Alignment(vertical="center")
        cell = sheet.cell(row=index, column=2, value=value if value != "" else None)
        cell.font = TEXT_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)

    accent = sheet.cell(row=1, column=2, value="организации города из двух карт в одной таблице")
    accent.font = Font(name="Calibri", size=11, color=ACCENT_DARK, italic=True)


def default_name(result: Result) -> str:
    """Имя файла: «Кофейня — Тюмень — 2026-10-24.xlsx»."""
    query = (result.settings.query or "все организации").strip().capitalize()
    stamp = (result.finished_at or datetime.now().astimezone()).strftime("%Y-%m-%d")
    safe = "".join(ch for ch in f"{query} — {result.settings.city.name} — {stamp}" if ch not in '\\/:*?"<>|')
    return f"{safe}.xlsx"


def write_default(result: Result, directory: Path) -> Path:
    return write(result, directory / default_name(result))
