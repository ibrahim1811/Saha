from datetime import date
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import weather
from app.weather import DayWeather, parse_metno, parse_openmeteo, summary

TZ = ZoneInfo("Europe/Istanbul")


def _om():
    temps = [10.0 + i * 0.5 for i in range(24)]
    return {
        "hourly": {"temperature_2m": temps},
        "daily": {
            "temperature_2m_min": [9.4],
            "temperature_2m_max": [21.6],
            "precipitation_probability_max": [55],
            "wind_speed_10m_max": [18.2],
            "weather_code": [61],
        },
    }


def _metno():
    series = []
    for h in range(4, 24):
        utc_hour = h - 3
        item = {
            "time": f"2026-10-10T{utc_hour:02d}:00:00Z",
            "data": {
                "instant": {"details": {"air_temperature": 10.0 + h, "wind_speed": 5.0 if h == 14 else 2.0}},
                "next_1_hours": {"summary": {"symbol_code": "partlycloudy_day" if h == 12 else "clearsky_day"},
                                 "details": {"precipitation_amount": 0.4 if h in (15, 16) else 0.0}},
            },
        }
        series.append(item)
    series.append({"time": "2026-10-10T21:00:00Z", "data": {"instant": {"details": {"air_temperature": 99, "wind_speed": 1}}}})
    return {"properties": {"timeseries": series}}


def test_openmeteo_parse():
    w = parse_openmeteo(_om())
    assert (w.t_min, w.t_max, w.t_morning, w.t_evening, w.rain_prob, w.wind_max) == (9.4, 21.6, 14.0, 19.5, 55, 18.2)
    assert len(w.hourly) == 24 and w.hourly[8] == 14.0
    assert w.condition == "rain"


def test_openmeteo_null_rain_is_zero():
    d = _om()
    d["daily"]["precipitation_probability_max"] = [None]
    assert parse_openmeteo(d).rain_prob == 0


def test_metno_parse_local_day():
    w = parse_metno(_metno(), date(2026, 10, 10), TZ)
    assert w.t_min == 14.0 and w.t_max == 33.0
    assert w.t_morning == 18.0 and w.t_evening == 29.0
    assert w.hourly[0] == 14.0 and w.hourly[23] == 33.0 and len(w.hourly) == 24
    assert w.wind_max == 18.0
    assert w.rain_prob == 40
    assert w.condition == "partly"


def test_metno_no_data_for_day_raises():
    with pytest.raises(ValueError):
        parse_metno(_metno(), date(2026, 10, 12), TZ)


@pytest.mark.parametrize("code,cond", [(0, "clear"), (2, "partly"), (3, "cloudy"), (45, "fog"), (81, "rain"), (73, "snow"), (95, "storm")])
def test_openmeteo_codes(code, cond):
    assert weather.condition_from_wmo(code) == cond


def test_summary():
    w = DayWeather(9.4, 21.6, 14.0, 19.5, 55, 18.2)
    assert summary(w) == "Sabah 14° → akşam 20° (en düşük 9°, en yüksek 22°), yağış %55, rüzgâr 18 km/s"


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_falls_back_to_metno_on_429(monkeypatch):
    monkeypatch.setattr(weather, "RETRY_DELAY", 0)
    monkeypatch.setattr(weather, "_today", lambda tz: date(2026, 10, 10))
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "api.open-meteo.com":
            return httpx.Response(429)
        assert "github.com/ibrahim1811/Saha" in request.headers["user-agent"]
        return httpx.Response(200, json=_metno())

    w = await weather.fetch(38.39, 27.17, "Europe/Istanbul", _client(handler))
    assert w.t_max == 33.0
    assert calls == ["api.open-meteo.com", "api.open-meteo.com", "api.met.no"]


async def test_fetch_uses_openmeteo_when_ok():
    w = await weather.fetch(38.39, 27.17, "Europe/Istanbul", _client(lambda r: httpx.Response(200, json=_om())))
    assert w.condition == "rain"


async def test_fetch_both_fail_raises(monkeypatch):
    monkeypatch.setattr(weather, "RETRY_DELAY", 0)
    with pytest.raises(Exception):
        await weather.fetch(38.39, 27.17, "Europe/Istanbul", _client(lambda r: httpx.Response(503)))
