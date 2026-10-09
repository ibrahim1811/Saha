import pytest

from app.intents import route


@pytest.mark.parametrize("text,expected", [
    ("yarın 15'te faturayı hatırlat", "reminder"),
    ("fizik ödevi cuma teslim", "task"),
    ("matematik sınavı 20 ekim", "task"),
    ("fizik yazılısı 20 ekim", "task"),
    ("fizik 1. yazılı 85", "grade"),
    ("kimya performans notum 90", "grade"),
    ("tyt deneme 78 net", "exam"),
    ("deneme: türkçe 32 mat 28 fen 10 sosyal 8", "exam"),
    ("bugün okula gitmedim", "absence"),
    ("dün özürlü devamsızlık yaptım", "absence"),
    ("devamsızlığım ne kadar?", None),
    ("sınavım kötü geçti", None),
    ("bugün ne var", None),
    ("matematikten 85 aldım", "grade"),
    ("matematik sınavından 85 aldım", "grade"),
    ("bugün fizikten 90 aldım", "grade"),
    ("yarın okula gitmeyeceğim", None),
])
def test_route(text, expected):
    assert route(text) == expected
