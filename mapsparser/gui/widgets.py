"""Кирпичики окна: карточка раздела, поля, кнопки, подсказка города."""

from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from . import theme


def wrap_to_width(container: ctk.CTkBaseClass, labels: list[ctk.CTkLabel], margin: int = 40) -> None:
    """Переносит текст по ширине окна: Tk сам переносит по числу пикселей, а не по месту."""

    def resize(event: object) -> None:
        scaling = ctk.ScalingTracker.get_widget_scaling(container)
        width = max(int(event.width / scaling) - margin, 200)
        for item in labels:
            item.configure(wraplength=width)

    container.bind("<Configure>", resize, add="+")


class SectionCard(ctk.CTkFrame):
    """Скруглённая карточка с заголовком; содержимое кладут в ``self.body``."""

    def __init__(self, master: ctk.CTkBaseClass, title: str, hint: str = "") -> None:
        super().__init__(
            master, fg_color=theme.CARD_BG, corner_radius=14, border_width=1, border_color=theme.CARD_BORDER
        )
        ctk.CTkLabel(self, text=title, font=theme.font(15, "bold"), text_color=theme.TEXT, anchor="w").pack(
            fill="x", padx=18, pady=(12, 0)
        )
        if hint:
            note = ctk.CTkLabel(
                self,
                text=hint,
                font=theme.font(12),
                text_color=theme.TEXT_MUTED,
                justify="left",
                anchor="w",
                wraplength=500,
            )
            note.pack(fill="x", padx=18, pady=(2, 0))
            wrap_to_width(self, [note])
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=18, pady=(8, 14))


def label(master: ctk.CTkBaseClass, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=text, font=theme.font(12), text_color=theme.TEXT_MUTED, anchor="w")


def entry(master: ctk.CTkBaseClass, placeholder: str = "", width: int = 160) -> ctk.CTkEntry:
    return ctk.CTkEntry(
        master,
        width=width,
        height=34,
        font=theme.font(13),
        border_width=1,
        fg_color=theme.INPUT_BG,
        border_color=theme.CARD_BORDER,
        text_color=theme.TEXT,
        placeholder_text=placeholder,
    )


def set_entry(widget: ctk.CTkEntry, value: object) -> None:
    text = "" if value in (None, "") else str(value)
    if widget.get() == text:
        return
    widget.delete(0, "end")
    if text:
        widget.insert(0, text)


def accent_button(
    master: ctk.CTkBaseClass, text: str, command: Callable[[], None], width: int = 150, **kwargs: object
) -> ctk.CTkButton:
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        width=width,
        height=36,
        font=theme.font(13, "bold"),
        fg_color=theme.ACCENT,
        hover_color=theme.ACCENT_HOVER,
        text_color=theme.ACCENT_TEXT,
        corner_radius=8,
        **kwargs,
    )


def neutral_button(
    master: ctk.CTkBaseClass, text: str, command: Callable[[], None], width: int = 120, **kwargs: object
) -> ctk.CTkButton:
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        width=width,
        height=34,
        font=theme.font(13),
        fg_color=theme.NEUTRAL_BUTTON,
        hover_color=theme.NEUTRAL_BUTTON_HOVER,
        text_color=theme.TEXT,
        corner_radius=8,
        **kwargs,
    )


def segmented(master: ctk.CTkBaseClass, values: list[str], command: Callable[[str], None]) -> ctk.CTkSegmentedButton:
    return ctk.CTkSegmentedButton(
        master,
        values=values,
        command=command,
        font=theme.font(12),
        height=32,
        selected_color=theme.ACCENT,
        selected_hover_color=theme.ACCENT_HOVER,
        unselected_color=theme.NEUTRAL_BUTTON,
        unselected_hover_color=theme.NEUTRAL_BUTTON_HOVER,
        text_color=theme.TEXT,
        fg_color=theme.NEUTRAL_BUTTON,
    )


def checkbox(master: ctk.CTkBaseClass, text: str, variable: ctk.BooleanVar, **kwargs: object) -> ctk.CTkCheckBox:
    return ctk.CTkCheckBox(
        master,
        text=text,
        variable=variable,
        font=theme.font(13),
        text_color=theme.TEXT,
        fg_color=theme.ACCENT,
        hover_color=theme.ACCENT_HOVER,
        checkmark_color=theme.ACCENT_TEXT,
        checkbox_width=18,
        checkbox_height=18,
        corner_radius=5,
        **kwargs,
    )


class Suggest(ctk.CTkToplevel):
    """Выпадающий список подсказок под полем ввода (города)."""

    def __init__(self, master: ctk.CTk, field: ctk.CTkEntry, lookup: Callable[[str], list[str]]) -> None:
        super().__init__(master, fg_color=theme.CARD_BG)
        self.overrideredirect(True)
        self.withdraw()
        self._field = field
        self._lookup = lookup
        self._buttons: list[ctk.CTkButton] = []
        self._frame = ctk.CTkFrame(self, fg_color=theme.CARD_BG, corner_radius=8, border_width=1,
                                   border_color=theme.CARD_BORDER)
        self._frame.pack(fill="both", expand=True)
        field.bind("<KeyRelease>", self._on_key, add="+")
        field.bind("<FocusOut>", lambda _: self.after(180, self.hide), add="+")

    def _on_key(self, event: object) -> None:
        if getattr(event, "keysym", "") in ("Return", "Tab", "Escape"):
            self.hide()
            return
        self.show(self._lookup(self._field.get()))

    def show(self, options: list[str]) -> None:
        for button in self._buttons:
            button.destroy()
        self._buttons.clear()
        text = self._field.get().strip()
        if not options or (len(options) == 1 and options[0] == text):
            self.hide()
            return
        for option in options[:8]:
            button = ctk.CTkButton(
                self._frame,
                text=option,
                anchor="w",
                height=28,
                font=theme.font(13),
                fg_color="transparent",
                hover_color=theme.NEUTRAL_BUTTON,
                text_color=theme.TEXT,
                corner_radius=6,
                command=lambda value=option: self._choose(value),
            )
            button.pack(fill="x", padx=4, pady=1)
            self._buttons.append(button)
        self._field.update_idletasks()
        x = self._field.winfo_rootx()
        y = self._field.winfo_rooty() + self._field.winfo_height() + 2
        self.geometry(f"{max(self._field.winfo_width(), 200)}x{len(self._buttons) * 30 + 8}+{x}+{y}")
        self.deiconify()
        self.lift()

    def _choose(self, value: str) -> None:
        set_entry(self._field, value)
        self.hide()
        self._field.focus_set()

    def hide(self) -> None:
        self.withdraw()
