import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from app import finance, news, outfit, weather
from app.schedule import format_lessons, lessons_for

log = logging.getLogger(__name__)

MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
SECTIONS = [
    ("weather", "🌤 Hava", "Hava"),
    ("lessons", "📚 Bugünün dersleri", "Ders programı"),
    ("finance", "💱 Piyasa", "Piyasa"),
    ("news", "📰 Haberler", "Haberler"),
]

Source = Callable[[], Awaitable[str]]


@dataclass
class Sources:
    weather: Source
    lessons: Source
    finance: Source
    news: Source


async def build(today: date, src: Sources) -> str:
    results = await asyncio.gather(*(getattr(src, attr)() for attr, _, _ in SECTIONS), return_exceptions=True)
    parts = [f"Günaydın Kayra! ☀️ {today.day} {MONTHS[today.month - 1]} {DAYS[today.weekday()]}"]
    for (attr, title, label), result in zip(SECTIONS, results):
        if isinstance(result, BaseException):
            log.error("Özet bölümü alınamadı: %s", attr, exc_info=result)
            result = f"⚠️ {label} alınamadı"
        parts.append(f"{title}\n{result}")
    return "\n\n".join(parts)


def make_sources(cfg, db, llm, http, today: date) -> Sources:
    async def weather_section() -> str:
        w = await weather.fetch(cfg.lat, cfg.lon, cfg.tz.key, http)
        return f"{weather.summary(w)}\n👕 {await outfit.advice(w, llm)}"

    async def lessons_section() -> str:
        return format_lessons(await lessons_for(today, db))

    return Sources(
        weather=weather_section,
        lessons=lessons_section,
        finance=lambda: finance.fetch(http),
        news=lambda: news.fetch(http),
    )
