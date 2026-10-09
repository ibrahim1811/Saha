from datetime import datetime
from zoneinfo import ZoneInfo

from app.chat import answer, build_context
from tests.fakes import FakeDB, FakeLLM

TZ = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 10, 9, 20, 0, tzinfo=TZ)
NOTES = [{"id": 1, "text": "Ahmet'e kitabı geri ver", "created_at": datetime(2026, 10, 5, 18, 30, tzinfo=TZ)}]


def test_context_has_date_notes_and_program():
    ctx = build_context(NOTES, {"okul": None, "cumartesi": None, "pazar": None}, NOW)
    assert "09.10.2026 20:00 (cuma)" in ctx
    assert "[05.10.2026 18:30] Ahmet'e kitabı geri ver" in ctx
    assert "🏫 Okul (hafta içi)" in ctx


def test_context_no_notes():
    assert "Henüz not yok." in build_context([], {}, NOW)


async def test_answer_passes_context_as_system():
    llm = FakeLLM(reply=" Ahmet'e kitabı vermen gerekiyordu. ")
    out = await answer("geçen hafta ne demiştim?", FakeDB(notes=NOTES), llm, NOW)
    assert out == "Ahmet'e kitabı vermen gerekiyordu."
    assert "Ahmet'e kitabı geri ver" in llm.calls[0]["system"]
    assert llm.calls[0]["prompt"] == "geçen hafta ne demiştim?"
