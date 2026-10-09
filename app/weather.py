from dataclasses import dataclass

import httpx

URL = "https://api.open-meteo.com/v1/forecast"


@dataclass(frozen=True)
class DayWeather:
    t_min: float
    t_max: float
    t_morning: float
    t_evening: float
    rain_prob: int
    wind_max: float


def parse(data: dict) -> DayWeather:
    daily = data["daily"]
    hourly = data["hourly"]["temperature_2m"]
    return DayWeather(
        t_min=daily["temperature_2m_min"][0],
        t_max=daily["temperature_2m_max"][0],
        t_morning=hourly[8],
        t_evening=hourly[19],
        rain_prob=int(daily["precipitation_probability_max"][0] or 0),
        wind_max=daily["wind_speed_10m_max"][0],
    )


async def fetch(lat: float, lon: float, tz_name: str, http: httpx.AsyncClient) -> DayWeather:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max,wind_speed_10m_max",
        "timezone": tz_name,
        "forecast_days": 1,
    }
    resp = await http.get(URL, params=params, timeout=10)
    resp.raise_for_status()
    return parse(resp.json())


def summary(w: DayWeather) -> str:
    return (
        f"Sabah {w.t_morning:.0f}° → akşam {w.t_evening:.0f}° "
        f"(en düşük {w.t_min:.0f}°, en yüksek {w.t_max:.0f}°), "
        f"yağış %{w.rain_prob}, rüzgâr {w.wind_max:.0f} km/s"
    )
