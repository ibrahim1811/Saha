from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.reminders import ReminderError, format_when, parse, parse_result
from tests.fakes import FakeLLM

TZ = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 10, 9, 20, 0, tzinfo=TZ)


def test_naive_time_gets_local_tz():
    when, text = parse_result({"when": "2026-10-10T15:00", "text": "faturayı öde"}, NOW)
    assert when == datetime(2026, 10, 10, 15, 0, tzinfo=TZ)
    assert text == "faturayı öde"


def test_llm_offset_ignored_wall_clock_kept():
    when, _ = parse_result({"when": "2026-10-10T15:00Z", "text": "x"}, NOW)
    assert when == datetime(2026, 10, 10, 15, 0, tzinfo=TZ)


def test_past_rejected():
    with pytest.raises(ReminderError, match="geçmişte"):
        parse_result({"when": "2026-10-09T19:59", "text": "x"}, NOW)


@pytest.mark.parametrize("data", [{}, {"when": "yarın", "text": "x"}, {"when": "2026-10-10T15:00", "text": " "}, []])
def test_bad_payload_rejected(data):
    with pytest.raises(ReminderError):
        parse_result(data, NOW)


async def test_parse_sends_now_and_day():
    llm = FakeLLM(reply='```json\n{"when": "2026-10-10T15:00", "text": "faturayı öde"}\n```')
    when, text = await parse("yarın 15'te faturayı hatırlat", NOW, llm)
    assert when.hour == 15 and text == "faturayı öde"
    assert "2026-10-09 20:00" in llm.calls[0]["prompt"] and "cuma" in llm.calls[0]["prompt"]


def test_format_when():
    assert format_when(datetime(2026, 10, 10, 15, 0, tzinfo=TZ)) == "10.10.2026 15:00"
