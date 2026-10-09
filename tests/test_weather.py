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
    assert w.hourly[:4] == (None, None, None, None) and w.hourly[4] == 14.0 and w.hourly[23] == 33.0 and len(w.hourly) == 24
    assert w.wind_max == 18.0
    assert w.rain_prob == 40
    assert w.rain_hours == (15, 16)
    assert w.condition == "partly"


def test_metno_partial_day_does_not_invent_morning():
    late = {"properties": {"timeseries": [
        {"time": "2026-10-09T19:00:00Z", "data": {"instant": {"details": {"air_temperature": 19.9, "wind_speed": 1}}}},
        {"time": "2026-10-09T20:00:00Z", "data": {"instant": {"details": {"air_temperature": 19.3, "wind_speed": 1}}}},
    ]}}
    w = parse_metno(late, date(2026, 10, 9), TZ)
    assert w.t_morning is None and w.t_evening is None
    assert [h for h, t in enumerate(w.hourly) if t is not None] == [22, 23]
    assert summary(w) == "En düşük 19°, en yüksek 20°, yağış %0, rüzgâr 4 km/s"


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
    assert calls == ["api.open-meteo.com", "api.met.no"]


async def test_fetch_uses_openmeteo_when_ok():
    w = await weather.fetch(38.39, 27.17, "Europe/Istanbul", _client(lambda r: httpx.Response(200, json=_om())))
    assert w.condition == "rain"


async def test_fetch_both_fail_raises(monkeypatch):
    monkeypatch.setattr(weather, "RETRY_DELAY", 0)
    with pytest.raises(Exception):
        await weather.fetch(38.39, 27.17, "Europe/Istanbul", _client(lambda r: httpx.Response(503)))


def _om2():
    today = [10.0] * 24
    tomorrow = [15, 15, 15, 15, 15, 15, 15, 15, 16, 19, 22, 24, 26, 28, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20]
    return {
        "hourly": {"temperature_2m": today + [float(t) for t in tomorrow]},
        "daily": {
            "temperature_2m_min": [9.0, 15.0],
            "temperature_2m_max": [12.0, 29.0],
            "precipitation_probability_max": [0, 10],
            "wind_speed_10m_max": [5.0, 12.0],
            "weather_code": [0, 2],
        },
    }


def test_openmeteo_second_day():
    w = parse_openmeteo(_om2(), 1)
    assert (w.t_min, w.t_max, w.t_morning, w.t_evening) == (15.0, 29.0, 16.0, 24.0)
    assert w.hourly[14] == 29.0 and w.condition == "partly"


async def test_fetch_tomorrow_openmeteo(monkeypatch):
    weather._CACHE.clear()
    monkeypatch.setattr(weather, "_today", lambda tz: date(2026, 10, 9))
    seen = {}

    def handler(request):
        seen["days"] = request.url.params["forecast_days"]
        return httpx.Response(200, json=_om2())

    w = await weather.fetch(38.39, 27.17, "Europe/Istanbul", _client(handler), date(2026, 10, 10))
    assert seen["days"] == "2" and w.t_max == 29.0


async def test_fetch_tomorrow_metno_fallback(monkeypatch):
    weather._CACHE.clear()
    monkeypatch.setattr(weather, "RETRY_DELAY", 0)
    monkeypatch.setattr(weather, "_today", lambda tz: date(2026, 10, 9))

    def handler(request):
        if request.url.host == "api.open-meteo.com":
            return httpx.Response(429)
        return httpx.Response(200, json=_metno())

    w = await weather.fetch(38.39, 27.17, "Europe/Istanbul", _client(handler), date(2026, 10, 10))
    assert w.t_max == 33.0


async def test_fetch_caches_success(monkeypatch):
    weather._CACHE.clear()
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=_om())

    c = _client(handler)
    await weather.fetch(38.39, 27.17, "Europe/Istanbul", c)
    await weather.fetch(38.39, 27.17, "Europe/Istanbul", c)
    assert len(calls) == 1


@pytest.fixture(autouse=True)
def _clear_cache():
    weather._CACHE.clear()



def test_openmeteo_rain_hours_from_hourly_probability():
    d = _om()
    d["hourly"]["precipitation_probability"] = [0] * 14 + [45, 60, 70, 30] + [0] * 6
    assert parse_openmeteo(d).rain_hours == (14, 15, 16)


def test_openmeteo_null_temperature_triggers_error():
    d = _om()
    d["daily"]["temperature_2m_max"] = [None]
    with pytest.raises(ValueError):
        parse_openmeteo(d)


async def test_openmeteo_5xx_still_retried(monkeypatch):
    monkeypatch.setattr(weather, "RETRY_DELAY", 0)
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "api.open-meteo.com" and len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=_om())

    await weather.fetch(38.39, 27.17, "Europe/Istanbul", _client(handler))
    assert calls == ["api.open-meteo.com", "api.open-meteo.com"]


@pytest.mark.parametrize("hours,prob,expected", [
    ((14, 15, 16, 19), 70, "☔ Yağmur bekleniyor: 14:00–17:00, 19:00–20:00 (ihtimal %70). Şemsiyeni hazırla."),
    ((), 50, "☔ Yağmur ihtimali %50. Şemsiyeni yanına al."),
    ((), 20, None),
])
def test_rain_warning(hours, prob, expected):
    w = DayWeather(10, 20, 12, 15, prob, 5, rain_hours=hours)
    assert weather.rain_warning(w) == expected


def test_rain_warning_skips_past_hours():
    w = DayWeather(10, 20, 12, 15, 70, 5, rain_hours=(2, 3, 15))
    assert weather.rain_warning(w, from_hour=7) == "☔ Yağmur bekleniyor: 15:00–16:00 (ihtimal %70). Şemsiyeni hazırla."
    assert weather.rain_warning(DayWeather(10, 20, 12, 15, 70, 5, rain_hours=(2, 3)), from_hour=7) is None


def test_metno_six_hour_block_marks_all_hours():
    data = {"properties": {"timeseries": [
        {"time": "2026-10-10T09:00:00Z", "data": {"instant": {"details": {"air_temperature": 20, "wind_speed": 1}},
                                                  "next_6_hours": {"summary": {"symbol_code": "rain"}, "details": {"precipitation_amount": 3.0}}}},
    ]}}
    assert parse_metno(data, date(2026, 10, 10), TZ).rain_hours == (12, 13, 14, 15, 16, 17)
