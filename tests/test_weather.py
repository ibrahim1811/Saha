from app.weather import DayWeather, parse, summary


def _data():
    temps = [10.0 + i * 0.5 for i in range(24)]
    return {
        "hourly": {"temperature_2m": temps},
        "daily": {
            "temperature_2m_min": [9.4],
            "temperature_2m_max": [21.6],
            "precipitation_probability_max": [55],
            "wind_speed_10m_max": [18.2],
        },
    }


def test_parse_picks_morning_and_evening():
    w = parse(_data())
    assert w == DayWeather(t_min=9.4, t_max=21.6, t_morning=14.0, t_evening=19.5, rain_prob=55, wind_max=18.2)


def test_parse_null_rain_is_zero():
    d = _data()
    d["daily"]["precipitation_probability_max"] = [None]
    assert parse(d).rain_prob == 0


def test_summary():
    w = DayWeather(9.4, 21.6, 14.0, 19.5, 55, 18.2)
    assert summary(w) == "Sabah 14° → akşam 20° (en düşük 9°, en yüksek 22°), yağış %55, rüzgâr 18 km/s"
