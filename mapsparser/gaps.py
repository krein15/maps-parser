"""Чего у фирмы нет — и насколько она поэтому интересна.

Обычный парсер карт выгружает то, что у фирмы есть: название, телефон, адрес.
Для холодных продаж ценнее обратное. Шесть фирм из пробного сбора: у двоих нет почты
вообще, у одного нет сайта при тридцати девяти отзывах — вот с чем к ним заходить.

Две оговорки, из-за которых пробелы считаются не «в лоб».

Первая: отсутствие данных в источнике и отсутствие данных у фирмы — разные вещи.
Яндекс не публикует почту никогда, поэтому «нет почты» можно написать, только если
фирму видел 2ГИС.

Вторая: «нет в 2ГИС» имеет смысл, лишь когда 2ГИС показал по запросу всё, что у него
есть. Если сбор упёрся в заданное число фирм, отсутствие ничего не доказывает —
и такой пробел не выписывается.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from .models import EMAIL, PHONE, SOCIAL_KINDS, TELEGRAM, VIBER, WEBSITE, WHATSAPP, Place
from .sources.base import Source

FEW_REVIEWS = 10
LOW_RATING = 4.0
MESSENGERS = (TELEGRAM, WHATSAPP, VIBER)
MAX_SCORE = 100


@dataclass(frozen=True)
class Context:
    """Условия сбора: без них пробел нельзя посчитать честно."""

    sources: tuple[Source, ...] = ()
    exhaustive: frozenset[str] = field(default_factory=frozenset)
    sites_checked: bool = False  # заходили ли на сайты фирм

    def saw(self, place: Place, kind: str) -> bool:
        """Видел ли фирму источник, который такой контакт вообще показывает."""
        return any(source.can_give(kind) and source.key in place.by_source for source in self.sources)

    def saw_any(self, place: Place, kinds: Iterable[str]) -> bool:
        kinds = tuple(kinds)
        return any(
            source.key in place.by_source and any(source.can_give(kind) for kind in kinds)
            for source in self.sources
        )


@dataclass(frozen=True)
class Gap:
    """Один вид пробела: как называется, сколько весит и чем проверяется."""

    code: str
    title: str  # как пробел называется в отчёте
    weight: int  # вклад в оценку, 0–100
    check: Callable[[Place, Context], bool]
    hint: str = ""  # с чем к фирме заходить

    def applies(self, place: Place, context: Context) -> bool:
        return self.check(place, context)


def _no_website(place: Place, context: Context) -> bool:
    return context.saw(place, WEBSITE) and not place.websites


def _no_email(place: Place, context: Context) -> bool:
    # Почту показывает только 2ГИС; но если программа ещё и зашла на сайт фирмы,
    # вывод «почты нет» становится обоснованным и без него.
    looked = context.saw(place, EMAIL) or (context.sites_checked and place.site is not None)
    return looked and not place.emails


def _site_dead(place: Place, _context: Context) -> bool:
    """Сайт у фирмы есть, но он не открывается или это заглушка хостера."""
    return place.site is not None and not place.site.alive and not place.site.bad_certificate


def _site_bad_certificate(place: Place, _context: Context) -> bool:
    return place.site is not None and place.site.bad_certificate


def _site_no_https(place: Place, _context: Context) -> bool:
    return place.site is not None and place.site.alive and not place.site.https


def _site_not_mobile(place: Place, _context: Context) -> bool:
    return place.site is not None and place.site.alive and not place.site.mobile


def _site_no_form(place: Place, _context: Context) -> bool:
    return place.site is not None and place.site.alive and not place.site.form


def _no_phone(place: Place, context: Context) -> bool:
    return context.saw(place, PHONE) and not place.phones


def _no_socials(place: Place, context: Context) -> bool:
    return context.saw_any(place, SOCIAL_KINDS) and not place.socials


def _no_messenger(place: Place, context: Context) -> bool:
    return context.saw_any(place, MESSENGERS) and not any(link.kind in MESSENGERS for link in place.socials)


def _missing_in(key: str) -> Callable[[Place, Context], bool]:
    def check(place: Place, context: Context) -> bool:
        if len(context.sources) < 2 or not any(source.key == key for source in context.sources):
            return False
        # Отсутствие доказывает что-то, только если карта показала всё по запросу.
        if key not in context.exhaustive:
            return False
        return key not in place.by_source

    return check


def _no_reviews(place: Place, _context: Context) -> bool:
    return place.reviews == 0


def _few_reviews(place: Place, _context: Context) -> bool:
    return 0 < place.reviews < FEW_REVIEWS


def _low_rating(place: Place, _context: Context) -> bool:
    rating = place.rating
    return rating is not None and rating < LOW_RATING


def _not_verified(place: Place, _context: Context) -> bool:
    """Владелец не подтвердил карточку: её никто не ведёт."""
    known = [c for c in place.companies if c.verified_owner is not None]
    return bool(known) and not any(c.verified_owner for c in known)


def _no_photos(place: Place, _context: Context) -> bool:
    known = [c.photos for c in place.companies if c.photos is not None]
    return bool(known) and max(known) == 0


def _no_schedule(place: Place, _context: Context) -> bool:
    return not place.schedule


GAPS: tuple[Gap, ...] = (
    Gap("website", "нет сайта", 30, _no_website, "сделать сайт или хотя бы страницу-визитку"),
    # Неработающий сайт — повод к разговору сильнее, чем его отсутствие: фирма уже платит
    # за хостинг и домен, просто не знает, что посетители туда не попадают.
    Gap("site_dead", "сайт не открывается", 28, _site_dead, "за домен платят, а сайта нет — поднять"),
    Gap(
        "site_cert", "ошибка сертификата на сайте", 18, _site_bad_certificate,
        "браузер встречает посетителя красным предупреждением",
    ),
    Gap("site_no_https", "сайт без https", 10, _site_no_https, "браузеры метят такой сайт небезопасным"),
    Gap("site_not_mobile", "сайт не для телефона", 14, _site_not_mobile, "с телефона заходит большинство"),
    Gap("site_no_form", "на сайте нет формы заявки", 8, _site_no_form, "заявку оставить негде"),
    Gap("email", "нет почты", 10, _no_email, "писать некуда — только звонок или мессенджер"),
    Gap("phone", "нет телефона", 6, _no_phone, "фирму нельзя набрать: заявки уходят к соседям"),
    Gap("socials", "нет соцсетей", 10, _no_socials, "нет площадки, где показывают работы"),
    Gap("messenger", "нет мессенджера", 5, _no_messenger, "заявку некуда написать с телефона"),
    Gap("no_yandex", "нет в Яндекс Картах", 12, _missing_in("yandex"), "фирму не находят в самой большой карте"),
    Gap("no_2gis", "нет в 2ГИС", 10, _missing_in("2gis"), "в 2ГИС её не видят вовсе"),
    Gap("no_reviews", "нет отзывов", 12, _no_reviews, "карточку никто не ведёт"),
    Gap("few_reviews", "мало отзывов", 8, _few_reviews, "отзывы не собирают"),
    Gap("low_rating", "рейтинг ниже 4", 6, _low_rating, "репутацию надо чинить"),
    Gap("unverified", "карточка не подтверждена", 8, _not_verified, "владелец не забрал карточку"),
    Gap("no_photos", "нет фотографий", 7, _no_photos, "фирму не видно глазами"),
    Gap("no_schedule", "не указан режим работы", 4, _no_schedule, "клиент не знает, когда приходить"),
)

GAP_BY_CODE: dict[str, Gap] = {gap.code: gap for gap in GAPS}
GAP_TITLES: dict[str, str] = {gap.code: gap.title for gap in GAPS}


def found_gaps(place: Place, context: Context) -> tuple[Gap, ...]:
    return tuple(gap for gap in GAPS if gap.applies(place, context))


def evaluate(place: Place, context: Context) -> tuple[tuple[str, ...], int]:
    """Пробелы фирмы и оценка 0–100: насколько она интересна для холодного захода."""
    found = found_gaps(place, context)
    score = min(MAX_SCORE, sum(gap.weight for gap in found))
    if not reachable(place):
        # Связаться не с кем — оценка не нужна, сколько бы пробелов ни нашлось.
        score = 0
    return tuple(gap.title for gap in found), score


def reachable(place: Place) -> bool:
    """Есть ли вообще способ связаться: телефон, почта или соцсеть."""
    return bool(place.phones or place.emails or place.socials)


def apply(places: Iterable[Place], context: Context) -> list[Place]:
    """Проставляет пробелы и оценку каждой фирме и сортирует по оценке."""
    result = list(places)
    for place in result:
        place.gaps, place.score = evaluate(place, context)
    result.sort(key=lambda p: (-p.score, -(p.reviews or 0), p.name))
    return result


def codes_for(place: Place, context: Context) -> tuple[str, ...]:
    """Коды пробелов — для фильтров и тестов."""
    return tuple(gap.code for gap in found_gaps(place, context))


def hints_for(titles: Iterable[str]) -> tuple[str, ...]:
    """Подсказки «с чем заходить» по названиям пробелов."""
    by_title = {gap.title: gap.hint for gap in GAPS}
    return tuple(by_title[title] for title in titles if by_title.get(title))
