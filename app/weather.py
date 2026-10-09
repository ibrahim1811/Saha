import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"
METNO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
METNO_UA = "saha-bot/1.0 github.com/ibrahim1811/Saha"
RETRY_DELAY = 1.0
CACHE_TTL = 900
RAIN_PROB_THRESHOLD = 40
_CACHE: dict[tuple, tuple[float, "DayWeather"]] = {}

CONDITION_TR = {
    "clear": "Açık",
    "partly": "Parçalı bulutlu",
    "cloudy": "Bulutlu",
    "fog": "Sisli",
    "rain": "Yağmurlu",
    "storm": "Fırtınalı",
    "snow": "Karlı",
}


@dataclass(frozen=True)
class DayWeather:
    t_min: float
    t_max: float
    t_morning: float | None
    t_evening: float | None
    rain_prob: int
    wind_max: float
    hourly: tuple[float | None, ...] = ()
    condition: str = ""
    rain_hours: tuple[int, ...] = ()


def condition_from_wmo(code: int | None) -> str:
    if code is None:
        return ""
    if code == 0:
        return "clear"
    if code in (1, 2):
        return "partly"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code >= 95:
        return "storm"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    return "rain"


def condition_from_symbol(symbol: str) -> str:
    for key, cond in (("thunder", "storm"), ("snow", "snow"), ("sleet", "snow"), ("rain", "rain"), ("fog", "fog"),
                      ("partlycloudy", "partly"), ("fair", "partly"), ("cloudy", "cloudy"), ("clearsky", "clear")):
        if key in symbol:
            return cond
    return ""


def parse_openmeteo(data: dict, index: int = 0) -> DayWeather:
    daily = data["daily"]
    hourly = data["hourly"]["temperature_2m"][24 * index : 24 * index + 24]
    probs = (data["hourly"].get("precipitation_probability") or [])[24 * index : 24 * index + 24]
    codes = daily.get("weather_code") or []
    if daily["temperature_2m_min"][index] is None or daily["temperature_2m_max"][index] is None or len(hourly) < 24:
        raise ValueError("Open-Meteo verisi eksik")
    return DayWeather(
        t_min=daily["temperature_2m_min"][index],
        t_max=daily["temperature_2m_max"][index],
        t_morning=hourly[8],
        t_evening=hourly[19],
        rain_prob=int(daily["precipitation_probability_max"][index] or 0),
        wind_max=daily["wind_speed_10m_max"][index],
        hourly=tuple(hourly),
        condition=condition_from_wmo(codes[index] if len(codes) > index else None),
        rain_hours=tuple(h for h, p in enumerate(probs) if p is not None and p >= RAIN_PROB_THRESHOLD),
    )


def parse_metno(data: dict, today: date, tz: ZoneInfo) -> DayWeather:
    temps: dict[int, float] = {}
    winds: list[float] = []
    precip = 0.0
    rain_hours: list[int] = []
    symbols: dict[int, str] = {}
    for item in data["properties"]["timeseries"]:
        local = datetime.fromisoformat(item["time"].replace("Z", "+00:00")).astimezone(tz)
        if local.date() != today:
            continue
        details = item["data"]["instant"]["details"]
        temps[local.hour] = details["air_temperature"]
        winds.append(details.get("wind_speed", 0.0) * 3.6)
        one = item["data"].get("next_1_hours")
        nxt = one or item["data"].get("next_6_hours") or {}
        amount = nxt.get("details", {}).get("precipitation_amount", 0.0)
        precip += amount
        if amount >= 0.1:
            span = 1 if one else 6
            rain_hours.extend(range(local.hour, min(24, local.hour + span)))
        if "summary" in nxt:
            symbols[local.hour] = nxt["summary"]["symbol_code"]
    if not temps:
        raise ValueError("MET Norway verisinde bugüne ait saat yok")
    symbol = symbols[min(symbols, key=lambda h: abs(h - 12))] if symbols else ""
    return DayWeather(
        t_min=min(temps.values()),
        t_max=max(temps.values()),
        t_morning=temps.get(8),
        t_evening=temps.get(19),
        rain_prob=0 if precip == 0 else (40 if precip < 1 else 70),
        wind_max=round(max(winds), 1),
        hourly=tuple(temps.get(h) for h in range(24)),
        condition=condition_from_symbol(symbol),
        rain_hours=tuple(sorted(set(rain_hours))),
    )


def _today(tz: ZoneInfo) -> date:
    return datetime.now(tz).date()


async def _openmeteo(lat: float, lon: float, tz_name: str, http: httpx.AsyncClient, offset: int = 0) -> DayWeather:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,precipitation_probability",
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max,wind_speed_10m_max,weather_code",
        "timezone": tz_name,
        "forecast_days": offset + 1,
    }
    for attempt in range(2):
        try:
            resp = await http.get(OPENMETEO_URL, params=params, timeout=10)
            resp.raise_for_status()
            return parse_openmeteo(resp.json(), offset)
        except httpx.HTTPError as e:
            rate_limited = isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429
            if attempt == 1 or rate_limited:
                raise
            await asyncio.sleep(RETRY_DELAY)
    raise RuntimeError("unreachable")


async def _metno(lat: float, lon: float, tz_name: str, http: httpx.AsyncClient, day: date) -> DayWeather:
    resp = await http.get(
        METNO_URL, params={"lat": round(lat, 2), "lon": round(lon, 2)}, headers={"User-Agent": METNO_UA}, timeout=10
    )
    resp.raise_for_status()
    return parse_metno(resp.json(), day, ZoneInfo(tz_name))


async def fetch(lat: float, lon: float, tz_name: str, http: httpx.AsyncClient, day: date | None = None) -> DayWeather:
    today = _today(ZoneInfo(tz_name))
    day = day or today
    key = (round(lat, 2), round(lon, 2), day)
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL:
        return cached[1]
    try:
        w = await _openmeteo(lat, lon, tz_name, http, (day - today).days)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as e:
        log.warning("Open-Meteo başarısız (%r), MET Norway deneniyor", e)
        w = await _metno(lat, lon, tz_name, http, day)
    _CACHE[key] = (time.monotonic(), w)
    return w


def summary(w: DayWeather) -> str:
    tail = f"yağış %{w.rain_prob}, rüzgâr {w.wind_max:.0f} km/s"
    if w.t_morning is not None and w.t_evening is not None:
        return f"Sabah {w.t_morning:.0f}° → akşam {w.t_evening:.0f}° (en düşük {w.t_min:.0f}°, en yüksek {w.t_max:.0f}°), {tail}"
    return f"En düşük {w.t_min:.0f}°, en yüksek {w.t_max:.0f}°, {tail}"


def _ranges(hours: tuple[int, ...]) -> list[str]:
    out, start, prev = [], None, None
    for h in sorted(hours):
        if start is None:
            start = prev = h
        elif h == prev + 1:
            prev = h
        else:
            out.append(f"{start:02d}:00–{prev + 1:02d}:00")
            start = prev = h
    if start is not None:
        out.append(f"{start:02d}:00–{prev + 1:02d}:00")
    return out


def rain_warning(w: DayWeather, from_hour: int = 0) -> str | None:
    hours = tuple(h for h in w.rain_hours if h >= from_hour)
    if hours:
        return f"☔ Yağmur bekleniyor: {', '.join(_ranges(hours))} (ihtimal %{w.rain_prob}). Şemsiyeni hazırla."
    if w.rain_hours:
        return None
    if w.rain_prob >= RAIN_PROB_THRESHOLD:
        return f"☔ Yağmur ihtimali %{w.rain_prob}. Şemsiyeni yanına al."
    return None
