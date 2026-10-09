import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from app import finance, news, outfit, weather
from app.schedule import format_lessons, lessons_for
from app.weather import DayWeather

log = logging.getLogger(__name__)

MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
SECTIONS = [
    ("weather", "🌤 Hava", "Hava"),
    ("lessons", "📚 Bugünün dersleri", "Ders programı"),
    ("finance", "💱 Piyasa", "Piyasa"),
    ("news", "📰 Haberler", "Haberler"),
]


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


@dataclass(frozen=True)
class Briefing:
    header: str
    text: str
    text_without_weather: str
    weather: WeatherInfo | None


def header(today: date) -> str:
    return f"Günaydın Kayra! ☀️ {today.day} {MONTHS[today.month - 1]} {DAYS[today.weekday()]}"


async def build(today: date, src: Sources, settings: dict) -> Briefing:
    enabled = [s for s in SECTIONS if settings["sections"].get(s[0])]
    results = await asyncio.gather(*(getattr(src, attr)() for attr, _, _ in enabled), return_exceptions=True)
    head = header(today)
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
    return Briefing(
        header=head,
        text="\n\n".join([head] + [p for _, p in parts]),
        text_without_weather="\n\n".join([head] + [p for a, p in parts if a != "weather"]),
        weather=info,
    )


def make_sources(cfg, db, llm, http, today: date, settings: dict) -> Sources:
    async def weather_section() -> WeatherInfo:
        w = await weather.fetch(cfg.lat, cfg.lon, cfg.tz.key, http, today)
        return WeatherInfo(w, await outfit.advice(w, llm), outfit.hints(w))

    async def lessons_section() -> str:
        return format_lessons(await lessons_for(today, db))

    return Sources(
        weather=weather_section,
        lessons=lessons_section,
        finance=lambda: finance.fetch(http),
        news=lambda: news.fetch(http, settings["news_count"]),
    )
