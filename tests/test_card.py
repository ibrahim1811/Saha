import io
from datetime import date

from PIL import Image

from app.card import render_card
from app.weather import DayWeather


def _open(data):
    return Image.open(io.BytesIO(data))


def test_renders_png_square():
    w = DayWeather(11, 27, 12, 22, 60, 31, tuple(10 + i * 0.7 for i in range(24)), "rain")
    data = render_card(w, ["ceket al", "şemsiye al"], date(2026, 10, 10))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert _open(data).size == (1080, 1080)


def test_renders_without_hourly_or_condition():
    w = DayWeather(18, 24, 19, 22, 0, 10)
    assert _open(render_card(w, [], date(2026, 10, 12))).size == (1080, 1080)


def test_all_conditions_render():
    for cond in ["clear", "partly", "cloudy", "fog", "rain", "storm", "snow", "weird"]:
        w = DayWeather(5, 9, 6, 8, 80, 40, tuple([7.0] * 24), cond)
        assert render_card(w, ["ceket al"], date(2026, 1, 1))[:4] == b"\x89PNG"


def test_turkish_capitalize():
    from app.card import tr_capitalize

    assert tr_capitalize("ince ve açık renkli giyin") == "İnce ve açık renkli giyin"
    assert tr_capitalize("ılık") == "Ilık"
    assert tr_capitalize("ceket al") == "Ceket al"
    assert tr_capitalize("") == ""
