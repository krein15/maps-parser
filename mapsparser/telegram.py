"""Отправка в Telegram: карточки новых фирм.

Токен бота и номер чата лежат в `.env` рядом с настройками программы и в git не
попадают. Токен — это пароль от бота: он не должен оказаться ни в журнале, ни в
сообщении об ошибке, поэтому всё, что пишется в лог, проходит через `SecretFilter`.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .models import Place
from .normalize import pretty_phone
from .settings import user_data_dir

API = "https://api.telegram.org"
TOKEN_KEY = "TELEGRAM_BOT_TOKEN"
CHAT_KEY = "TELEGRAM_CHAT_ID"
TIMEOUT = 20.0
MAX_MESSAGE = 3800  # у Telegram предел 4096, оставляем запас на разметку

_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")

log = logging.getLogger(__name__)


class TelegramError(RuntimeError):
    """Телеграм не принял запрос. Текст можно показывать пользователю."""


class SecretFilter(logging.Filter):
    """Вырезает токен из всего, что уходит в журнал."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _TOKEN_RE.sub("…токен скрыт…", str(record.msg))
        return True


@dataclass(frozen=True)
class Account:
    """Куда отправлять."""

    token: str = ""
    chat: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.token and self.chat)


def env_file() -> Path:
    return user_data_dir() / ".env"


def load_account() -> Account:
    """Токен и чат из .env рядом с настройками программы."""
    import os

    values: dict[str, str] = {}
    path = env_file()
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    key, _, value = line.partition("=")
                    values[key.strip()] = value.strip()
        except OSError:
            log.warning("Файл %s не читается", path)
    token = values.get(TOKEN_KEY) or os.environ.get(TOKEN_KEY, "")
    chat = values.get(CHAT_KEY) or os.environ.get(CHAT_KEY, "")
    return Account(token=token.strip(), chat=chat.strip())


def save_account(account: Account) -> Path:
    path = env_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Настройки Карты Парсер. Токен — это пароль от бота, никому его не показывайте.\n"
        "# Токен выдаёт @BotFather в Telegram, номер чата подскажет «Найти мой чат».\n"
        f"{TOKEN_KEY}={account.token}\n{CHAT_KEY}={account.chat}\n",
        encoding="utf-8",
    )
    return path


def _call(token: str, method: str, payload: dict[str, object] | None = None) -> dict:
    if not _TOKEN_RE.fullmatch(token or ""):
        raise TelegramError("это не похоже на токен бота: он выглядит как 123456789:AAE… — скопируйте его целиком")
    url = f"{API}/bot{token}/{method}"
    data = urllib.parse.urlencode(payload or {}).encode("utf-8")
    request = urllib.request.Request(url, data=data if payload else None)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            answer = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            described = json.loads(body).get("description", "")
        except json.JSONDecodeError:
            described = body[:200]
        raise TelegramError(f"Telegram ответил {exc.code}: {described}") from exc
    except OSError as exc:
        raise TelegramError(f"Telegram недоступен: {exc}") from exc
    if not answer.get("ok"):
        raise TelegramError(str(answer.get("description", "неизвестная ошибка")))
    return answer.get("result", {})


def check_token(token: str) -> str:
    """Проверяет токен и возвращает имя бота."""
    result = _call(token, "getMe")
    return str(result.get("username", ""))


def find_chat(token: str) -> str:
    """Номер чата из последних сообщений боту: пользователь пишет боту «привет», мы его видим."""
    updates = _call(token, "getUpdates", {"limit": 10, "timeout": 0})
    for update in reversed(updates if isinstance(updates, list) else []):
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        if chat.get("id"):
            return str(chat["id"])
    raise TelegramError("Сообщений боту нет. Напишите ему в Telegram «привет» и нажмите кнопку ещё раз.")


def send(account: Account, text: str, *, preview: bool = False) -> None:
    """Отправляет сообщение. Длинный текст режется на части по строкам."""
    if not account.ready:
        raise TelegramError("Не заданы токен бота или номер чата")
    for part in _split(text):
        _call(
            account.token,
            "sendMessage",
            {
                "chat_id": account.chat,
                "text": part,
                "parse_mode": "HTML",
                "disable_web_page_preview": "false" if preview else "true",
            },
        )


def _split(text: str) -> list[str]:
    if len(text) <= MAX_MESSAGE:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > MAX_MESSAGE:
            parts.append(current)
            current = ""
        current += line
    if current:
        parts.append(current)
    return parts


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def card(place: Place) -> str:
    """Карточка фирмы для сообщения: что это, как связаться и чего ей не хватает."""
    lines = [f"<b>{_escape(place.name)}</b>"]
    if place.rubrics:
        lines.append(_escape(", ".join(place.rubrics[:2])))
    if place.address:
        lines.append("📍 " + _escape(place.address))
    contacts = []
    if place.phones:
        contacts.append(pretty_phone(place.phones[0]))
    if place.emails:
        contacts.append(place.emails[0])
    if place.websites:
        contacts.append(place.websites[0])
    if contacts:
        lines.append("☎ " + _escape(" · ".join(contacts)))
    if place.gaps:
        lines.append("❗ " + _escape(", ".join(place.gaps)))
    links = [f'<a href="{place.url(key)}">{"2ГИС" if key == "2gis" else "Яндекс"}</a>'
             for key in sorted(place.by_source) if place.url(key)]
    if links:
        lines.append(" · ".join(links))
    return "\n".join(lines)


def new_places_message(city: str, query: str, places: list[Place]) -> str:
    """Сообщение о новых фирмах в нише."""
    head = f"<b>Новые фирмы: {_escape(query)}, {_escape(city)}</b>\nНашлось: {len(places)}"
    cards = "\n\n".join(card(place) for place in places)
    return f"{head}\n\n{cards}"
