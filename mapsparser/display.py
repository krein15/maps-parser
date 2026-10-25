"""Мелочи для читаемых сообщений: числа со словами в правильном падеже."""

from __future__ import annotations


def plural(count: int, one: str, few: str, many: str) -> str:
    """plural(24, "участок", "участка", "участков") → «24 участка»."""
    tens, units = count % 100, count % 10
    if units == 1 and tens != 11:
        word = one
    elif 2 <= units <= 4 and not 12 <= tens <= 14:
        word = few
    else:
        word = many
    return f"{count} {word}"
