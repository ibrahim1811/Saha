import copy
from datetime import date

from app.briefing import Sources, WeatherInfo, build
from app.settings import DEFAULTS
from app.weather import DayWeather

W = WeatherInfo(DayWeather(11, 27, 12, 22, 0, 10), "İnce ceket al.", ["ceket al"])


def _ok(value):
    async def f():
        return value
    return f


async def _boom():
    raise RuntimeError("api down")


def _src(**over):
    base = dict(weather=_ok(W), lessons=_ok("• Mat"), finance=_ok("Dolar: 41"), news=_ok("• Haber"))
    base.update(over)
    return Sources(**base)


def _settings(**sections):
    s = copy.deepcopy(DEFAULTS)
    s["sections"].update(sections)
    return s


async def test_all_sections_in_order():
    b = await build(date(2026, 10, 9), _src(), _settings())
    assert b.text.startswith("Günaydın Kayra! ☀️ 9 Ekim Cuma")
    assert b.text.index("🌤 Hava\nSabah 12°") < b.text.index("📚 Bugünün dersleri\n• Mat") < b.text.index("💱 Piyasa") < b.text.index("📰 Haberler")
    assert "👕 İnce ceket al." in b.text
    assert b.weather is W
    assert "🌤 Hava" not in b.text_without_weather and "📚 Bugünün dersleri" in b.text_without_weather


async def test_failed_section_does_not_break_others(caplog):
    b = await build(date(2026, 10, 9), _src(weather=_boom, finance=_boom), _settings())
    assert "🌤 Hava\n⚠️ Hava alınamadı" in b.text
    assert "💱 Piyasa\n⚠️ Piyasa alınamadı" in b.text
    assert "• Mat" in b.text and "• Haber" in b.text
    assert b.weather is None
    assert "api down" in caplog.text


async def test_disabled_sections_not_called_or_shown():
    b = await build(date(2026, 10, 9), _src(news=_boom, finance=_boom), _settings(news=False, finance=False))
    assert "📰" not in b.text and "💱" not in b.text
    assert "alınamadı" not in b.text
