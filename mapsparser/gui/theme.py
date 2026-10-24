"""Цвета и шрифты окна — из фирменного набора krein. Пары значений: (светлая тема, тёмная)."""

from __future__ import annotations

import sys
from pathlib import Path

import customtkinter as ctk

# Фон и текст взяты прямо из набора: ink #0a0c0f, paper #f4f3ee, акцент #5cf28e / #0c9a4a.
APP_BG = ("#F4F3EE", "#0A0C0F")
CARD_BG = ("#FFFFFF", "#141820")
CARD_BORDER = ("#D9D5CA", "#2A323C")
INPUT_BG = ("#FAF9F5", "#1B212A")
TEXT = ("#121418", "#E9ECEF")
TEXT_MUTED = ("#6F7680", "#7C8692")
ACCENT = ("#0C9A4A", "#5CF28E")
ACCENT_HOVER = ("#096F36", "#3FD873")
# На ярко-зелёной кнопке белые буквы не читаются — в тёмной теме пишем по ней чернилами.
ACCENT_TEXT = ("#FFFFFF", "#0A0C0F")
NEUTRAL_BUTTON = ("#E7E4DA", "#222A33")
NEUTRAL_BUTTON_HOVER = ("#DAD6C9", "#2D3640")
DANGER = ("#C23B2E", "#F0776A")
WARNING = ("#B45309", "#F2B457")
SUCCESS = ("#0C9A4A", "#5CF28E")

# Цвета карт — их собственные, чтобы источник узнавался с одного взгляда.
SOURCE_COLORS = {
    "2gis": ("#0F8C45", "#36C978"),
    "yandex": ("#D23417", "#FF6A4D"),
}

FONT_FAMILY = "Segoe UI"
MONO_FAMILY = "Consolas"


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


def mono(size: int = 12, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=MONO_FAMILY, size=size, weight=weight)


def source_color(key: str) -> tuple[str, str]:
    return SOURCE_COLORS.get(key, TEXT_MUTED)


def score_color(score: int) -> tuple[str, str]:
    """Чем больше у фирмы пробелов, тем заметнее её оценка."""
    if score >= 60:
        return ACCENT
    if score >= 30:
        return WARNING
    return TEXT_MUTED


def resource_path(relative: str) -> Path:
    """Путь к файлу рядом с программой — и из исходников, и из собранного exe."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / relative
