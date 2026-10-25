"""Вежливый загрузчик страниц.

Один поток, пауза между запросами, повтор при сетевой ошибке, уважение к `Retry-After`.
Карты открытые, но нагрузка на них должна оставаться на уровне обычного посетителя:
парсер, который бьёт в сто потоков, ломает сам себя — сначала капча, потом блокировка.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

from .cache import Cache

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


@dataclass(frozen=True)
class Page:
    """Ответ страницы целиком: текст, код и адрес после всех переадресаций."""

    text: str
    status: int
    url: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 400


class FetchError(RuntimeError):
    """Страницу получить не удалось."""


class Stopped(RuntimeError):
    """Сбор остановлен пользователем."""


class Fetcher:
    """Качает страницы по одной, с паузой и повторами."""

    def __init__(
        self,
        *,
        delay: float = 1.5,
        retries: int = 3,
        timeout: float = 30.0,
        cache: Cache | None = None,
        log: Callable[[str], None] | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> None:
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.cache = cache
        self.log = log or (lambda _message: None)
        self.stop = stop or (lambda: False)
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.requests_made = 0
        self.from_cache = 0
        self._last_request_at = 0.0

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def check_stop(self) -> None:
        if self.stop():
            raise Stopped("сбор остановлен")

    def _wait_turn(self) -> None:
        """Держит паузу между запросами, разбавляя её случайной добавкой."""
        if not self._last_request_at:
            return
        pause = self.delay + random.uniform(0, self.delay * 0.4)
        waited = time.monotonic() - self._last_request_at
        remaining = pause - waited
        while remaining > 0:
            self.check_stop()
            time.sleep(min(remaining, 0.25))
            remaining = pause - (time.monotonic() - self._last_request_at)

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> str:
        """Возвращает текст страницы. Берёт из кэша, если он есть и не протух."""
        self.check_stop()
        if self.cache:
            cached = self.cache.get(url)
            if cached is not None:
                self.from_cache += 1
                return cached

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self.check_stop()
            self._wait_turn()
            self._last_request_at = time.monotonic()
            try:
                response = self.session.get(url, timeout=self.timeout, headers=headers)
            except requests.RequestException as exc:
                last_error = exc
                self.log(f"Сеть молчит ({type(exc).__name__}), попытка {attempt} из {self.retries}")
                self._sleep_before_retry(attempt)
                continue

            self.requests_made += 1
            if response.status_code == 429:
                pause = self._retry_after(response, attempt)
                self.log(f"Карта просит подождать {pause:.0f} с")
                self._sleep(pause)
                last_error = FetchError("слишком частые запросы (429)")
                continue
            if response.status_code >= 500:
                last_error = FetchError(f"сервер ответил {response.status_code}")
                self.log(f"Сервер ответил {response.status_code}, попытка {attempt} из {self.retries}")
                self._sleep_before_retry(attempt)
                continue
            if response.status_code == 404:
                raise FetchError(f"страницы нет: {url}")
            if response.status_code != 200:
                raise FetchError(f"неожиданный ответ {response.status_code}: {url}")

            text = response.text
            if self.cache:
                self.cache.put(url, text)
            return text

        raise FetchError(f"не удалось получить {url}: {last_error}")

    def post(self, url: str, data: dict[str, str], *, timeout: float = 30.0) -> str:
        """Отправляет форму. Нужно реестру ЕГРЮЛ: он выдаёт талон на поиск."""
        self.check_stop()
        self._wait_turn()
        self._last_request_at = time.monotonic()
        headers = {"X-Requested-With": "XMLHttpRequest", "Referer": url}
        try:
            response = self.session.post(url, data=data, timeout=timeout, headers=headers)
        except requests.RequestException as exc:
            raise FetchError(f"{type(exc).__name__}") from exc
        self.requests_made += 1
        if response.status_code != 200:
            raise FetchError(f"ответ {response.status_code}: {url}")
        return response.text

    def probe(self, url: str, *, timeout: float = 10.0) -> Page:
        """Одна попытка без повторов: нужна для чужих сайтов.

        Ошибку сервера здесь не считаем бедой — наоборот, неработающий сайт фирмы
        это и есть результат проверки, поэтому код ответа возвращается как есть.
        Ответ кладётся в кэш вместе с кодом: повторный сбор по той же нише не должен
        заново обходить сотню чужих сайтов и ждать на каждом мёртвом по десять секунд.
        """
        self.check_stop()
        key = f"probe:{url}"
        if self.cache:
            cached = self.cache.get(key)
            if cached is not None:
                self.from_cache += 1
                head, _, text = cached.partition("\n")
                status, _, final = head.partition(" ")
                return Page(text=text, status=int(status or 0), url=final or url)
        self._wait_turn()
        self._last_request_at = time.monotonic()
        try:
            response = self.session.get(url, timeout=timeout, allow_redirects=True)
        except requests.RequestException as exc:
            raise FetchError(f"{type(exc).__name__}") from exc
        self.requests_made += 1
        page = Page(text=response.text, status=response.status_code, url=response.url)
        if self.cache:
            self.cache.put(key, f"{page.status} {page.url}\n{page.text}")
        return page

    def _retry_after(self, response: requests.Response, attempt: int) -> float:
        raw = response.headers.get("Retry-After", "")
        try:
            return max(1.0, float(raw))
        except ValueError:
            return min(60.0, self.delay * 4 * attempt)

    def _sleep_before_retry(self, attempt: int) -> None:
        self._sleep(min(30.0, self.delay * attempt * 2))

    def _sleep(self, seconds: float) -> None:
        remaining = seconds
        while remaining > 0:
            self.check_stop()
            step = min(remaining, 0.25)
            time.sleep(step)
            remaining -= step
