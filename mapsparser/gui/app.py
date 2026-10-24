"""Окно программы: три шага — город, ниша, «Найти фирмы» — и готовый Excel.

Мерка простая: человек, который впервые открыл программу, должен получить таблицу
за пять минут и без инструкции. Поэтому на первом экране только три поля, а всё
остальное — объём сбора, паузы, папка — спрятано во вкладку «Настройки» с рабочими
значениями по умолчанию.

Сбор идёт в отдельном потоке, а разговаривает с окном через очередь: Tk не терпит,
когда его трогают не из главного потока.
"""

from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from .. import __version__
from ..cache import Cache
from ..cities import City, find, suggest
from ..csvout import write as write_csv
from ..excel import write_default
from ..http import Stopped
from ..models import LINK_TITLES, Place
from ..normalize import pretty_phone
from ..pipeline import Result, Settings, run
from ..settings import APP_TITLE, BRAND, default_cache_dir, default_output_dir
from ..sources import all_sources, get
from .preferences import SIZE_LIMITS, SIZES, Preferences
from .theme import (
    ACCENT,
    APP_BG,
    CARD_BG,
    CARD_BORDER,
    DANGER,
    TEXT,
    TEXT_MUTED,
    font,
    mono,
    resource_path,
    score_color,
    source_color,
)
from .widgets import (
    SectionCard,
    Suggest,
    accent_button,
    checkbox,
    entry,
    label,
    neutral_button,
    segmented,
    set_entry,
    wrap_to_width,
)

BRAND_URL = "https://kreinstudio.ru/"
ICON_SIZE = (44, 44)
LOGO_SIZE = (233, 46)  # полный логотип 1651×326 с полем: рисунок 213 px — минимум из набора 200
SEARCH_TAB, RESULTS_TAB, SETTINGS_TAB = "Поиск", "Результаты", "Настройки"
MAX_CARDS = 80
SUBTITLE = "Организации города из 2ГИС и Яндекс Карт — с контактами и колонкой «чего у фирмы нет»"

FIRST_STEPS = (
    "Как начать:\n"
    "1. Впишите город.\n"
    "2. Впишите, кого ищем, — или выберите нишу из списка.\n"
    "3. Нажмите «Найти фирмы»: отчёт Excel откроется сам.\n\n"
    "Здесь будет виден ход сбора."
)

# Ниши, с которых обычно начинают холодный обзвон.
NICHES = (
    "кофейня",
    "ресторан",
    "автосервис",
    "автомойка",
    "шиномонтаж",
    "стоматология",
    "медицинский центр",
    "ветеринарная клиника",
    "салон красоты",
    "барбершоп",
    "фитнес-клуб",
    "детский центр",
    "автошкола",
    "языковая школа",
    "строительная компания",
    "ремонт квартир",
    "натяжные потолки",
    "пластиковые окна",
    "мебель на заказ",
    "клининговая компания",
    "грузоперевозки",
    "типография",
    "цветы",
    "юридические услуги",
    "бухгалтерские услуги",
    "кадровое агентство",
    "агентство недвижимости",
    "турагентство",
)


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__(fg_color=APP_BG)
        self.prefs = Preferences.load()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.result: Result | None = None
        self.last_report: Path | None = None
        self._closing = False

        self.title(f"{APP_TITLE} {__version__}")
        self._size_window(1180, 780)
        icon = resource_path("assets/icon.ico")
        if icon.exists():
            self.after(250, lambda: self.iconbitmap(str(icon)))  # CTk сбрасывает значок сразу после старта

        self._build_header()
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        content.grid_columnconfigure(0, weight=3, uniform="columns")
        content.grid_columnconfigure(1, weight=2, uniform="columns")
        content.grid_rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(
            content,
            fg_color="transparent",
            corner_radius=12,
            anchor="nw",
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT,
            text_color=TEXT,
        )
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        self._build_search_tab(self.tabs.add(SEARCH_TAB))
        self._build_results_tab(self.tabs.add(RESULTS_TAB))
        self._build_settings_tab(self.tabs.add(SETTINGS_TAB))
        self.tabs.set(SEARCH_TAB)
        self._build_run_panel(content)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_events)

    # ------------------------------------------------------------------ разметка

    def _size_window(self, width: int, height: int) -> None:
        """Вписывает окно в экран: при масштабе Windows запрошенный размер вырастает."""
        try:
            scaling = ctk.ScalingTracker.get_window_scaling(self)
        except Exception:
            scaling = 1.0
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(width, int(screen_width / scaling) - 40)
        height = min(height, int(screen_height / scaling) - 90)
        x = max((screen_width - int(width * scaling)) // 2, 0)
        y = max((screen_height - int(height * scaling)) // 3, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(980, width), min(600, height))

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(18, 14))
        icon = _brand_image("icon-dark-512.png", "icon-dark-512.png", ICON_SIZE)
        if icon:
            ctk.CTkLabel(header, image=icon, text="").pack(side="left")
        else:  # из исходников без Pillow
            ctk.CTkLabel(
                header, text=">_", width=44, height=44, corner_radius=12, fg_color="#0A0C0F",
                text_color="#5CF28E", font=font(17, "bold"),
            ).pack(side="left")

        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left", padx=12)
        name = ctk.CTkFrame(titles, fg_color="transparent")
        name.pack(anchor="w")
        ctk.CTkLabel(name, text=APP_TITLE, font=font(21, "bold"), text_color=TEXT).pack(side="left")
        author = ctk.CTkLabel(name, text=f"by {BRAND}", font=font(13), text_color=TEXT_MUTED, cursor="hand2")
        author.pack(side="left", padx=(8, 0), pady=(6, 0))
        author.bind("<Button-1>", lambda _: webbrowser.open(BRAND_URL))
        ctk.CTkLabel(titles, text=SUBTITLE, font=font(13), text_color=TEXT_MUTED).pack(anchor="w")

        image = _brand_image("logo-light@2x.png", "logo-dark@2x.png", LOGO_SIZE)
        logo = ctk.CTkLabel(header, image=image, text="", cursor="hand2") if image else None
        if logo:
            logo.pack(side="right")
            logo.bind("<Button-1>", lambda _: webbrowser.open(BRAND_URL))
        self.appearance = segmented(header, ["Светлая", "Тёмная", "Системная"], self._set_appearance)
        self.appearance.set(self.prefs.appearance)
        self.appearance.pack(side="right", padx=(0, 12 if logo else 0))
        self._set_appearance(self.prefs.appearance)

    def _build_search_tab(self, tab: ctk.CTkBaseClass) -> None:
        card = SectionCard(tab, "Найти фирмы", "Три шага: город, кого ищем — и кнопка. Отчёт откроется сам.")
        card.pack(fill="x")
        grid = ctk.CTkFrame(card.body, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure(1, weight=1)
        row = iter(range(10))

        def field(text: str, widget: ctk.CTkBaseClass) -> None:
            number = next(row)
            ctk.CTkLabel(grid, text=text, font=font(13, "bold"), text_color=TEXT, anchor="w").grid(
                row=number, column=0, sticky="w", padx=(0, 14), pady=6
            )
            widget.grid(row=number, column=1, sticky="ew", pady=6)

        self.city = entry(grid, "Тюмень")
        set_entry(self.city, self.prefs.city)
        field("Город", self.city)
        self.city_hint = Suggest(self, self.city, lambda text: [c.name for c in suggest(text, 8)])

        query_row = ctk.CTkFrame(grid, fg_color="transparent")
        query_row.grid_columnconfigure(0, weight=1)
        self.query = entry(query_row, "кофейня")
        set_entry(self.query, self.prefs.query)
        self.query.grid(row=0, column=0, sticky="ew")
        self.niche = ctk.CTkOptionMenu(
            query_row,
            values=["Ниша…", *NICHES],
            width=150,
            height=34,
            font=font(13),
            command=self._pick_niche,
            fg_color=CARD_BORDER,
            button_color=CARD_BORDER,
            text_color=TEXT,
            dropdown_font=font(13),
        )
        self.niche.set("Ниша…")
        self.niche.grid(row=0, column=1, padx=(10, 0))
        field("Кого ищем", query_row)

        self.size = segmented(grid, list(SIZES), lambda _value: None)
        self.size.set(self.prefs.size)
        field("Сколько собирать", self.size)

        sources_row = ctk.CTkFrame(grid, fg_color="transparent")
        self.source_vars: dict[str, ctk.BooleanVar] = {}
        for source in all_sources():
            var = ctk.BooleanVar(value=source.key in self.prefs.sources)
            self.source_vars[source.key] = var
            box = checkbox(sources_row, source.title, var)
            box.configure(text_color=source_color(source.key))
            box.pack(side="left", padx=(0, 16))
        field("Карты", sources_row)

        self.only_without_site = ctk.BooleanVar(value=self.prefs.only_without_site)
        checkbox(card.body, "Только те, у кого нет сайта", self.only_without_site).pack(anchor="w", pady=(10, 0))

        buttons = ctk.CTkFrame(card.body, fg_color="transparent")
        buttons.pack(fill="x", pady=(16, 0))
        self.find_button = accent_button(buttons, "Найти фирмы", self._start, width=170)
        self.find_button.pack(side="left")
        self.open_button = neutral_button(buttons, "Открыть отчёт", self._open_report, width=150)
        self.open_button.pack(side="left", padx=10)
        self.open_button.configure(state="disabled")

        hint = ctk.CTkLabel(
            card.body,
            text=(
                "Данные берутся с открытых страниц карт — ни ключей, ни регистрации не нужно. "
                "Сбор идёт по одному запросу с паузой, как у обычного посетителя, поэтому город "
                "целиком занимает минуты, а не секунды."
            ),
            font=font(12),
            text_color=TEXT_MUTED,
            justify="left",
            anchor="w",
            wraplength=520,
        )
        hint.pack(fill="x", pady=(14, 0))
        wrap_to_width(card.body, [hint], margin=10)

    def _build_results_tab(self, tab: ctk.CTkBaseClass) -> None:
        self.results_header = ctk.CTkLabel(
            tab,
            text="Здесь появятся найденные фирмы: нажмите «Найти фирмы».",
            font=font(13),
            text_color=TEXT_MUTED,
            anchor="w",
            justify="left",
        )
        self.results_header.pack(fill="x", pady=(0, 8))
        wrap_to_width(tab, [self.results_header], margin=10)
        self.results = ctk.CTkScrollableFrame(
            tab, fg_color="transparent", corner_radius=0, scrollbar_button_color=CARD_BORDER
        )
        self.results.pack(fill="both", expand=True)

    def _build_settings_tab(self, tab: ctk.CTkBaseClass) -> None:
        card = SectionCard(tab, "Как собирать", "Значения по умолчанию подходят большинству.")
        card.pack(fill="x")
        body = card.body

        self.deep = ctk.BooleanVar(value=self.prefs.deep)
        checkbox(
            body, "Открывать карточки 2ГИС ради почты (медленнее, но находятся e-mail)", self.deep
        ).pack(anchor="w", pady=4)
        self.use_cache = ctk.BooleanVar(value=self.prefs.use_cache)
        checkbox(body, "Помнить скачанные страницы сутки", self.use_cache).pack(anchor="w", pady=4)
        self.open_report = ctk.BooleanVar(value=self.prefs.open_report)
        checkbox(body, "Открывать отчёт сразу после сбора", self.open_report).pack(anchor="w", pady=4)

        delay_row = ctk.CTkFrame(body, fg_color="transparent")
        delay_row.pack(fill="x", pady=(10, 4))
        label(delay_row, "Пауза между запросами, секунды").pack(side="left")
        self.delay = entry(delay_row, "1,5", width=80)
        set_entry(self.delay, str(self.prefs.delay).replace(".", ","))
        self.delay.pack(side="left", padx=10)

        folder_row = ctk.CTkFrame(body, fg_color="transparent")
        folder_row.pack(fill="x", pady=(10, 4))
        neutral_button(folder_row, "Папка отчётов…", self._pick_folder, width=150).pack(side="left")
        self.folder_label = ctk.CTkLabel(folder_row, text="", font=font(12), text_color=TEXT_MUTED, anchor="w")
        self.folder_label.pack(side="left", padx=10, fill="x", expand=True)
        self._show_folder()

        cache_card = SectionCard(tab, "Сохранённые страницы", "Кэш лежит рядом с настройками программы.")
        cache_card.pack(fill="x", pady=(14, 0))
        cache_row = ctk.CTkFrame(cache_card.body, fg_color="transparent")
        cache_row.pack(fill="x")
        neutral_button(cache_row, "Очистить", self._clear_cache, width=120).pack(side="left")
        self.cache_label = ctk.CTkLabel(cache_row, text="", font=font(12), text_color=TEXT_MUTED)
        self.cache_label.pack(side="left", padx=12)
        self._show_cache()

        about = SectionCard(tab, "Откуда данные", "")
        about.pack(fill="x", pady=(14, 0))
        for source in all_sources():
            line = ctk.CTkLabel(
                about.body,
                text=f"{source.title} — {source.note}",
                font=font(12),
                text_color=TEXT_MUTED,
                anchor="w",
                justify="left",
                wraplength=500,
            )
            line.pack(fill="x", pady=2)
            wrap_to_width(about.body, [line], margin=10)

    def _build_run_panel(self, content: ctk.CTkFrame) -> None:
        panel = ctk.CTkFrame(
            content, fg_color=CARD_BG, corner_radius=14, border_width=1, border_color=CARD_BORDER
        )
        panel.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(panel, text="Ход работы", font=font(15, "bold"), text_color=TEXT, anchor="w").pack(
            fill="x", padx=18, pady=(12, 6)
        )
        self.log = ctk.CTkTextbox(
            panel, font=mono(12), fg_color="transparent", text_color=TEXT, wrap="word", border_width=0
        )
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.log.insert("1.0", FIRST_STEPS)
        self.log.configure(state="disabled")

        buttons = ctk.CTkFrame(panel, fg_color="transparent")
        buttons.pack(fill="x", padx=18, pady=(0, 14))
        self.stop_button = neutral_button(buttons, "Остановить", self._stop, width=130)
        self.stop_button.pack(side="left")
        self.stop_button.configure(state="disabled")
        self.csv_button = neutral_button(buttons, "Ещё и CSV", self._save_csv, width=120)
        self.csv_button.pack(side="right")
        self.csv_button.configure(state="disabled")

    # ------------------------------------------------------------------ сбор

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        city_name = self.city.get().strip()
        city = find(city_name)
        if not city:
            self._say(f"Город «{city_name}» не нашёлся. Подсказки появляются при вводе.", "error")
            close = suggest(city_name, 5)
            if close:
                self._say("Может быть: " + ", ".join(c.name for c in close))
            return
        query = self.query.get().strip()
        if not query:
            self._say("Впишите, кого ищем: «кофейня», «автосервис» — или выберите нишу.", "error")
            return
        keys = [key for key, var in self.source_vars.items() if var.get()]
        if not keys:
            self._say("Выберите хотя бы одну карту.", "error")
            return

        settings = Settings(
            query=query,
            city=city,
            sources=[get(key) for key in keys],
            limit=SIZE_LIMITS.get(self.size.get(), 300),
            deep=self.deep.get(),
            delay=self._delay_value(),
            use_cache=self.use_cache.get(),
            required_gaps=("website",) if self.only_without_site.get() else (),
        )
        self._remember(city, query)
        self._clear_log()
        self._say(f"Ищу «{query}» в городе {city.name}. Это займёт несколько минут.")
        self.cancel.clear()
        self.find_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.open_button.configure(state="disabled")
        self.csv_button.configure(state="disabled")
        self.worker = threading.Thread(target=self._work, args=(settings,), daemon=True)
        self.worker.start()

    def _work(self, settings: Settings) -> None:
        """Поток сбора. С окном разговаривает только через очередь."""
        try:
            result = run(
                settings,
                log=lambda message: self.events.put(("log", ("info", message))),
                stop=self.cancel.is_set,
            )
            report = None
            if result.places:
                directory = Path(self.prefs.output_dir) if self.prefs.output_dir else default_output_dir()
                report = write_default(result, directory)
            self.events.put(("done", (result, report)))
        except Stopped:
            self.events.put(("stopped", None))
        except Exception as error:
            self.events.put(("error", str(error)))

    def _stop(self) -> None:
        self.cancel.set()
        self._say("Останавливаю: сохраню то, что успели собрать.")
        self.stop_button.configure(state="disabled")

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    level, message = payload
                    self._say(message, level)
                elif kind == "done":
                    self._finished(*payload)
                elif kind == "stopped":
                    self._say("Остановлено.", "warning")
                    self._idle()
                elif kind == "error":
                    self._say(f"Не получилось: {payload}", "error")
                    self._idle()
        except queue.Empty:
            pass
        if not self._closing:
            self.after(120, self._poll_events)

    def _finished(self, result: Result, report: Path | None) -> None:
        self.result = result
        self.last_report = report
        self._show_places(result)
        self._idle()
        if not result.places:
            self._say("Ничего не нашлось. Попробуйте другое слово или снимите фильтр.", "warning")
            return
        self.csv_button.configure(state="normal")
        if report:
            self.open_button.configure(state="normal")
            self._say(f"Отчёт: {report}")
            if self.open_report.get():
                _open_path(report)
        self.tabs.set(RESULTS_TAB)

    def _idle(self) -> None:
        self.find_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self._show_cache()

    # ------------------------------------------------------------------ результаты

    def _show_places(self, result: Result) -> None:
        for child in self.results.winfo_children():
            child.destroy()
        places = result.places
        shown = places[:MAX_CARDS]
        tail = f" Показаны первые {len(shown)} — остальные в отчёте." if len(places) > len(shown) else ""
        self.results_header.configure(
            text=(
                f"Нашлось фирм: {len(places)}. В обеих картах: {result.in_both}. "
                f"Запросов к картам: {result.requests}.{tail}"
            ),
            text_color=TEXT,
        )
        for place in shown:
            self._place_card(place)

    def _place_card(self, place: Place) -> None:
        card = ctk.CTkFrame(
            self.results, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=CARD_BORDER
        )
        card.pack(fill="x", pady=4, padx=2)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(10, 2))
        ctk.CTkLabel(
            top, text=str(place.score), font=font(15, "bold"), text_color=score_color(place.score), width=34
        ).pack(side="left")
        title = ctk.CTkLabel(top, text=place.name, font=font(14, "bold"), text_color=TEXT, anchor="w")
        title.pack(side="left", fill="x", expand=True)
        for key in sorted(place.by_source):
            address = place.url(key)
            link = ctk.CTkLabel(top, text=_source_title(key), font=font(11), text_color=source_color(key),
                                cursor="hand2")
            link.pack(side="right", padx=(8, 0))
            link.bind("<Button-1>", lambda _event, url=address: webbrowser.open(url))

        if place.gaps:
            gaps = ctk.CTkLabel(
                card, text="Чего нет: " + ", ".join(place.gaps), font=font(12), text_color=DANGER,
                anchor="w", justify="left", wraplength=420,
            )
            gaps.pack(fill="x", padx=14)
            wrap_to_width(card, [gaps], margin=30)

        contacts = " · ".join(
            part
            for part in (
                pretty_phone(place.phones[0]) if place.phones else "",
                place.emails[0] if place.emails else "",
                place.websites[0] if place.websites else "",
            )
            if part
        )
        if contacts:
            ctk.CTkLabel(card, text=contacts, font=mono(12), text_color=TEXT, anchor="w").pack(fill="x", padx=14)
        if place.socials:
            names = ", ".join(LINK_TITLES.get(link.kind, link.kind) for link in place.socials)
            ctk.CTkLabel(card, text=f"соцсети: {names}", font=font(11), text_color=TEXT_MUTED, anchor="w").pack(
                fill="x", padx=14
            )

        rating = f"★ {place.rating} ({place.reviews})" if place.rating else "без оценок"
        bottom = " · ".join(part for part in (place.address, rating, place.schedule) if part)
        line = ctk.CTkLabel(
            card, text=bottom, font=font(11), text_color=TEXT_MUTED, anchor="w", justify="left", wraplength=420
        )
        line.pack(fill="x", padx=14, pady=(0, 10))
        wrap_to_width(card, [line], margin=30)

    # ------------------------------------------------------------------ мелочи

    def _pick_niche(self, value: str) -> None:
        if value != "Ниша…":
            set_entry(self.query, value)
            self.niche.set("Ниша…")

    def _delay_value(self) -> float:
        try:
            return max(0.3, float(self.delay.get().replace(",", ".")))
        except ValueError:
            return 1.5

    def _pick_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Куда складывать отчёты")
        if chosen:
            self.prefs.output_dir = chosen
            self._show_folder()

    def _show_folder(self) -> None:
        self.folder_label.configure(text=str(self.prefs.output_dir or default_output_dir()))

    def _show_cache(self) -> None:
        cache = Cache(default_cache_dir())
        self.cache_label.configure(text=f"занято {cache.size_mb()} МБ")

    def _clear_cache(self) -> None:
        removed = Cache(default_cache_dir()).clear()
        self._say(f"Кэш очищен: удалено страниц {removed}.")
        self._show_cache()

    def _save_csv(self) -> None:
        if not (self.result and self.last_report):
            return
        path = write_csv(self.result, self.last_report.with_suffix(".csv"))
        self._say(f"CSV: {path}")

    def _open_report(self) -> None:
        if self.last_report:
            _open_path(self.last_report)

    def _say(self, message: str, level: str = "info") -> None:
        prefix = {"error": "✖ ", "warning": "• ", "info": ""}.get(level, "")
        self.log.configure(state="normal")
        self.log.insert("end", f"{prefix}{message}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _set_appearance(self, value: str) -> None:
        self.prefs.appearance = value
        ctk.set_appearance_mode({"Светлая": "light", "Тёмная": "dark"}.get(value, "system"))

    def _remember(self, city: City, query: str) -> None:
        self.prefs.city = city.name
        self.prefs.query = query
        self.prefs.size = self.size.get()
        self.prefs.sources = [key for key, var in self.source_vars.items() if var.get()]
        self.prefs.deep = self.deep.get()
        self.prefs.only_without_site = self.only_without_site.get()
        self.prefs.use_cache = self.use_cache.get()
        self.prefs.open_report = self.open_report.get()
        self.prefs.delay = self._delay_value()

    def _on_close(self) -> None:
        self._closing = True
        self.cancel.set()
        with contextlib.suppress(OSError):
            self.prefs.save()
        self.destroy()


def _source_title(key: str) -> str:
    for source in all_sources():
        if source.key == key:
            return source.title
    return key


def _brand_image(light: str, dark: str, size: tuple[int, int]) -> ctk.CTkImage | None:
    """Картинка из фирменного набора (assets/brand) для светлой и тёмной темы."""
    try:
        from PIL import Image
    except ImportError:  # из исходников без Pillow окно работает, только без картинок
        return None
    paths = [resource_path(f"assets/brand/{name}") for name in (light, dark)]
    if not all(path.exists() for path in paths):
        return None
    return ctk.CTkImage(light_image=Image.open(paths[0]), dark_image=Image.open(paths[1]), size=size)


def _open_path(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(path)], check=False)
    except OSError:
        pass


def main() -> None:
    ctk.set_default_color_theme("blue")  # цвета всё равно задаются поимённо, тема нужна как основа
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
