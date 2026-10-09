import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"
METNO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
METNO_UA = "saha-bot/1.0 github.com/ibrahim1811/Saha"
RETRY_DELAY = 1.0

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
    t_morning: float
    t_evening: float
    rain_prob: int
    wind_max: float
    hourly: tuple[float, ...] = ()
    condition: str = ""


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


def parse_openmeteo(data: dict) -> DayWeather:
    daily = data["daily"]
    hourly = data["hourly"]["temperature_2m"]
    return DayWeather(
        t_min=daily["temperature_2m_min"][0],
        t_max=daily["temperature_2m_max"][0],
        t_morning=hourly[8],
        t_evening=hourly[19],
        rain_prob=int(daily["precipitation_probability_max"][0] or 0),
        wind_max=daily["wind_speed_10m_max"][0],
        hourly=tuple(hourly[:24]),
        condition=condition_from_wmo(daily.get("weather_code", [None])[0]),
    )


def _fill(values: dict[int, float]) -> list[float]:
    known = sorted(values)
    return [values[min(known, key=lambda k: (abs(k - h), k))] for h in range(24)]


def parse_metno(data: dict, today: date, tz: ZoneInfo) -> DayWeather:
    temps: dict[int, float] = {}
    winds: list[float] = []
    precip = 0.0
    symbols: dict[int, str] = {}
    for item in data["properties"]["timeseries"]:
        local = datetime.fromisoformat(item["time"].replace("Z", "+00:00")).astimezone(tz)
        if local.date() != today:
            continue
        details = item["data"]["instant"]["details"]
        temps[local.hour] = details["air_temperature"]
        winds.append(details.get("wind_speed", 0.0) * 3.6)
        nxt = item["data"].get("next_1_hours") or item["data"].get("next_6_hours") or {}
        precip += nxt.get("details", {}).get("precipitation_amount", 0.0)
        if "summary" in nxt:
            symbols[local.hour] = nxt["summary"]["symbol_code"]
    if not temps:
        raise ValueError("MET Norway verisinde bugüne ait saat yok")
    hourly = _fill(temps)
    symbol = symbols[min(symbols, key=lambda h: abs(h - 12))] if symbols else ""
    return DayWeather(
        t_min=min(temps.values()),
        t_max=max(temps.values()),
        t_morning=hourly[8],
        t_evening=hourly[19],
        rain_prob=0 if precip == 0 else (40 if precip < 1 else 70),
        wind_max=round(max(winds), 1),
        hourly=tuple(hourly),
        condition=condition_from_symbol(symbol),
    )


def _today(tz: ZoneInfo) -> date:
    return datetime.now(tz).date()


async def _openmeteo(lat: float, lon: float, tz_name: str, http: httpx.AsyncClient) -> DayWeather:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max,wind_speed_10m_max,weather_code",
        "timezone": tz_name,
        "forecast_days": 1,
    }
    for attempt in range(2):
        try:
            resp = await http.get(OPENMETEO_URL, params=params, timeout=10)
            resp.raise_for_status()
            return parse_openmeteo(resp.json())
        except httpx.HTTPError:
            if attempt == 1:
                raise
            await asyncio.sleep(RETRY_DELAY)
    raise RuntimeError("unreachable")


async def _metno(lat: float, lon: float, tz_name: str, http: httpx.AsyncClient) -> DayWeather:
    resp = await http.get(
        METNO_URL, params={"lat": round(lat, 2), "lon": round(lon, 2)}, headers={"User-Agent": METNO_UA}, timeout=10
    )
    resp.raise_for_status()
    tz = ZoneInfo(tz_name)
    return parse_metno(resp.json(), _today(tz), tz)


async def fetch(lat: float, lon: float, tz_name: str, http: httpx.AsyncClient) -> DayWeather:
    try:
        return await _openmeteo(lat, lon, tz_name, http)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as e:
        log.warning("Open-Meteo başarısız (%r), MET Norway deneniyor", e)
    return await _metno(lat, lon, tz_name, http)


def summary(w: DayWeather) -> str:
    return (
        f"Sabah {w.t_morning:.0f}° → akşam {w.t_evening:.0f}° "
        f"(en düşük {w.t_min:.0f}°, en yüksek {w.t_max:.0f}°), "
        f"yağış %{w.rain_prob}, rüzgâr {w.wind_max:.0f} km/s"
    )
