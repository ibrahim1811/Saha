from datetime import date

import pytest

from app.schedule import (
    ScheduleError, day_key, format_all, format_lessons, lessons_for, read_photo, validate_dershane, validate_okul,
)
from tests.fakes import FakeDB, FakeLLM

OKUL = {
    "pazartesi": [{"saat": "08:30", "ders": "Matematik"}, {"saat": "", "ders": "Fizik"}],
    "salı": [],
    "çarşamba": [{"saat": "09:20", "ders": "Kimya"}],
    "perşembe": [],
    "cuma": [{"saat": "08:30", "ders": "Tarih"}],
}


def test_validate_okul_fills_missing_days():
    out = validate_okul({"pazartesi": [{"saat": 830, "ders": " Mat "}]})
    assert out["pazartesi"] == [{"saat": "830", "ders": "Mat"}]
    assert out["cuma"] == []


def test_validate_okul_all_empty_raises():
    with pytest.raises(ScheduleError):
        validate_okul({"pazartesi": []})


def test_validate_bad_item_raises():
    with pytest.raises(ScheduleError):
        validate_okul({"pazartesi": [{"saat": "08:30"}]})
    with pytest.raises(ScheduleError):
        validate_dershane({"ders": "Fizik"})


def test_day_key():
    assert day_key(date(2026, 10, 12)) == "pazartesi"
    assert day_key(date(2026, 10, 17)) == "cumartesi"
    assert day_key(date(2026, 10, 18)) == "pazar"


async def test_lessons_weekday_from_okul():
    db = FakeDB({("okul", ""): OKUL})
    assert await lessons_for(date(2026, 10, 14), db) == [{"saat": "09:20", "ders": "Kimya"}]


async def test_lessons_saturday_from_dershane():
    sat = [{"saat": "10:00", "ders": "Türkçe"}]
    db = FakeDB({("okul", ""): OKUL, ("dershane", "cumartesi"): sat})
    assert await lessons_for(date(2026, 10, 17), db) == sat


async def test_lessons_missing_schedule_is_none():
    assert await lessons_for(date(2026, 10, 18), FakeDB({("okul", ""): OKUL})) is None
    assert await lessons_for(date(2026, 10, 12), FakeDB()) is None


def test_format_lessons():
    assert format_lessons(None).startswith("Bu gün için kayıtlı program yok")
    assert format_lessons([]) == "Bugün ders yok 🎉"
    assert format_lessons(OKUL["pazartesi"]) == "• 08:30 Matematik\n• Fizik"


def test_format_all_marks_missing():
    text = format_all({"okul": OKUL, "cumartesi": None, "pazar": [{"saat": "", "ders": "Mat"}]})
    assert "Pazartesi:\n• 08:30 Matematik" in text
    assert "Dershane Cumartesi:\nBu gün için kayıtlı program yok" in text
    assert "Dershane Pazar:\n• Mat" in text


async def test_read_photo_dershane():
    llm = FakeLLM(reply='```json\n[{"saat": "09:00", "ders": "Fizik"}]\n```')
    assert await read_photo(b"img", "dershane", llm) == [{"saat": "09:00", "ders": "Fizik"}]
    assert llm.calls[0]["image"] == b"img"


async def test_read_photo_okul_unreadable_raises():
    with pytest.raises(Exception):
        await read_photo(b"img", "okul", FakeLLM(reply="Fotoğraf çok bulanık."))


from app.schedule import merge_lessons, merge_okul, start_minutes


@pytest.mark.parametrize("saat,expected", [("15:50", 950), ("9.30", 570), ("15:50-16:30", 950), ("08:30 - 09:10", 510), ("", None), ("öğle", None)])
def test_start_minutes(saat, expected):
    assert start_minutes(saat) == expected


def test_merge_sorts_by_start_time():
    first = [{"saat": "13:30-14:10", "ders": "Fizik"}, {"saat": "14:30-15:10", "ders": "Kimya"}]
    second = [{"saat": "15:50-16:30", "ders": "Biyoloji"}, {"saat": "09:00-09:40", "ders": "Mat"}]
    assert [l["ders"] for l in merge_lessons(first, second)] == ["Mat", "Fizik", "Kimya", "Biyoloji"]


def test_merge_skips_duplicates_and_keeps_timeless_last():
    old = [{"saat": "10:00", "ders": "Türkçe"}, {"saat": "", "ders": "Etüt"}]
    new = [{"saat": "10:00", "ders": "Türkçe"}, {"saat": "09:00", "ders": "Mat"}]
    assert merge_lessons(old, new) == [{"saat": "09:00", "ders": "Mat"}, {"saat": "10:00", "ders": "Türkçe"}, {"saat": "", "ders": "Etüt"}]


def test_merge_with_nothing_sorts_new():
    assert [l["ders"] for l in merge_lessons(None, [{"saat": "11:00", "ders": "B"}, {"saat": "08:00", "ders": "A"}])] == ["A", "B"]


def test_merge_okul_per_day():
    old = {**{d: [] for d in ["pazartesi", "salı", "çarşamba", "perşembe", "cuma"]}, "pazartesi": [{"saat": "08:30", "ders": "Mat"}]}
    new = {**{d: [] for d in ["pazartesi", "salı", "çarşamba", "perşembe", "cuma"]}, "pazartesi": [{"saat": "13:00", "ders": "Fizik"}], "cuma": [{"saat": "09:00", "ders": "Tarih"}]}
    out = merge_okul(old, new)
    assert [l["ders"] for l in out["pazartesi"]] == ["Mat", "Fizik"]
    assert out["cuma"] == [{"saat": "09:00", "ders": "Tarih"}]
    assert merge_okul(None, new)["cuma"][0]["ders"] == "Tarih"
