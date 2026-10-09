from app.outfit import advice, hints
from app.weather import DayWeather
from tests.fakes import FakeLLM


def w(**kw):
    base = dict(t_min=18, t_max=24, t_morning=19, t_evening=22, rain_prob=0, wind_max=10)
    base.update(kw)
    return DayWeather(**base)


def test_mild_day_no_hints():
    assert hints(w()) == []


def test_jacket_boundary():
    assert "ceket al" in hints(w(t_min=14.9))
    assert "ceket al" not in hints(w(t_min=15))


def test_umbrella_boundary():
    assert "şemsiye al" in hints(w(rain_prob=40))
    assert "şemsiye al" not in hints(w(rain_prob=39))


def test_layers_boundary():
    assert "katmanlı giyin" in hints(w(t_min=16, t_max=24))
    assert "katmanlı giyin" not in hints(w(t_min=17, t_max=24))


def test_wind_and_heat():
    h = hints(w(wind_max=30, t_max=28, t_min=21))
    assert "rüzgârlık iyi olur" in h and "ince ve açık renkli giyin" in h


async def test_advice_uses_llm_and_passes_hints():
    llm = FakeLLM(reply="  İnce ceket al.  ")
    assert await advice(w(t_min=10), llm) == "İnce ceket al."
    assert "ceket al" in llm.calls[0]["prompt"]


async def test_advice_falls_back_on_llm_error():
    llm = FakeLLM(exc=RuntimeError("down"))
    assert await advice(w(t_min=10, rain_prob=70), llm) == "• ceket al\n• şemsiye al\n• katmanlı giyin"


async def test_advice_fallback_mild():
    assert await advice(w(), FakeLLM(exc=RuntimeError())) == "Hava ılıman, rahat giyinebilirsin."
