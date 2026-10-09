import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta

from app import finance, news, outfit, tasks, weather
from app.schedule import format_lessons, lessons_for
from app.weather import DayWeather

log = logging.getLogger(__name__)

MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
SECTIONS = [
    ("weather", "🌤 Hava", "Hava"),
    ("lessons", "📚 Bugünün dersleri", "Ders programı"),
    ("tasks", "📌 Ödev ve sınavlar", "Ödev ve sınavlar"),
    ("finance", "💱 Piyasa", "Piyasa"),
    ("news", "📰 Haberler", "Haberler"),
]
EVENING_SECTIONS = {"weather", "lessons", "tasks"}


@dataclass(frozen=True)
class WeatherInfo:
    w: DayWeather
    advice: str
    hints: list[str]

    def text(self) -> str:
        return f"{weather.summary(self.w)}\n👕 {self.advice}"


@dataclass
class Sources:
    weather: Callable[[], Awaitable[WeatherInfo]]
    lessons: Callable[[], Awaitable[str]]
    finance: Callable[[], Awaitable[str]]
    news: Callable[[], Awaitable[str]]
    tasks: Callable[[], Awaitable[str]]


@dataclass(frozen=True)
class Briefing:
    header: str
    text: str
    text_without_weather: str
    weather: WeatherInfo | None


def header(today: date, evening: bool = False) -> str:
    day = f"{today.day} {MONTHS[today.month - 1]} {DAYS[today.weekday()]}"
    return f"🌙 İyi geceler Kayra! Yarın {day}" if evening else f"Günaydın Kayra! ☀️ {day}"


async def build(today: date, src: Sources, settings: dict, evening: bool = False, from_hour: int = 0) -> Briefing:
    enabled = [s for s in SECTIONS if settings["sections"].get(s[0]) and (not evening or s[0] in EVENING_SECTIONS)]
    if evening:
        enabled = [(a, t.replace("Bugünün", "Yarının"), l) for a, t, l in enabled]
    show_weather = any(a == "weather" for a, _, _ in enabled)
    fetch = enabled if show_weather else [SECTIONS[0]] + enabled
    results = await asyncio.gather(*(getattr(src, attr)() for attr, _, _ in fetch), return_exceptions=True)
    if not show_weather:
        hidden, results = results[0], results[1:]
        alert_info = hidden if isinstance(hidden, WeatherInfo) else None
        if isinstance(hidden, BaseException):
            log.warning("Yağmur uyarısı için hava alınamadı: %r", hidden)
    else:
        alert_info = None
    head = header(today, evening)
    parts: list[tuple[str, str]] = []
    info = None
    for (attr, title, label), result in zip(enabled, results):
        if isinstance(result, BaseException):
            log.error("Özet bölümü alınamadı: %s", attr, exc_info=result)
            body = f"⚠️ {label} alınamadı"
        elif attr == "weather":
            info = result
            body = result.text()
        else:
            body = result
        parts.append((attr, f"{title}\n{body}"))
    top = [head]
    source = info or alert_info
    alert = weather.rain_warning(source.w, from_hour) if source else None
    if alert:
        top.append(alert)
    return Briefing(
        header=head,
        text="\n\n".join(top + [p for _, p in parts]),
        text_without_weather="\n\n".join(top + [p for a, p in parts if a != "weather"]),
        weather=info,
    )


def make_sources(cfg, db, llm, http, today: date, settings: dict, ref_day: date | None = None) -> Sources:
    async def weather_section() -> WeatherInfo:
        w = await weather.fetch(cfg.lat, cfg.lon, cfg.tz.key, http, today)
        return WeatherInfo(w, await outfit.advice(w, llm), outfit.hints(w))

    async def lessons_section() -> str:
        return format_lessons(await lessons_for(today, db))

    async def tasks_section() -> str:
        items = await db.upcoming_tasks(today + timedelta(days=7))
        return tasks.format_tasks(items, ref_day or today)

    return Sources(
        weather=weather_section,
        lessons=lessons_section,
        finance=lambda: finance.fetch(http),
        news=lambda: news.fetch(http, settings["news_count"]),
        tasks=tasks_section,
    )
