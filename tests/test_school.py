from datetime import date

import pytest

from app.school import (
    NotThis, SchoolError, absence_status, absence_totals, averages, exam_summary, parse_absence_result,
    parse_exam_result, parse_grade_result, subject_hours,
)

OKUL = {
    "pazartesi": [{"saat": "08:30", "ders": "Matematik"}, {"saat": "09:20", "ders": "Matematik"}, {"saat": "10:10", "ders": "Fizik"}],
    "salı": [{"saat": "08:30", "ders": "matematik"}],
    "çarşamba": [], "perşembe": [{"saat": "", "ders": "Kimya"}], "cuma": [],
}


def test_parse_grade():
    assert parse_grade_result({"subject": " Fizik ", "label": "1. yazılı", "score": 85}) == ("Fizik", "1. yazılı", 85.0)
    with pytest.raises(NotThis):
        parse_grade_result({"subject": None})
    for bad in ({"subject": "Fizik", "label": "x", "score": 120}, {"subject": "", "label": "x", "score": 50}, {}, []):
        with pytest.raises(SchoolError):
            parse_grade_result(bad)


def test_subject_hours_casefold():
    assert subject_hours(OKUL) == {"matematik": 3, "fizik": 1, "kimya": 1}
    assert subject_hours(None) == {}


def test_weighted_average():
    grades = [
        {"id": 1, "subject": "Matematik", "label": "1. yazılı", "score": 60},
        {"id": 2, "subject": "matematik", "label": "2. yazılı", "score": 80},
        {"id": 3, "subject": "Fizik", "label": "1. yazılı", "score": 100},
        {"id": 4, "subject": "Tarih", "label": "1. yazılı", "score": 50},
    ]
    subjects, overall = averages(grades, subject_hours(OKUL))
    assert [(s["subject"], s["average"], s["hours"]) for s in subjects] == [("Fizik", 100.0, 1), ("Matematik", 70.0, 3), ("Tarih", 50.0, 1)]
    assert overall == pytest.approx((70 * 3 + 100 + 50) / 5)
    assert averages([], {}) == ([], None)


def test_parse_absence():
    today = date(2026, 10, 10)
    assert parse_absence_result({"day": "2026-10-09", "excused": True, "half": False}, today) == (date(2026, 10, 9), True, False)
    with pytest.raises(NotThis):
        parse_absence_result({"day": None}, today)
    with pytest.raises(SchoolError):
        parse_absence_result({"day": "2026-10-11", "excused": False, "half": False}, today)


def test_absence_totals_and_status():
    rows = [{"excused": False, "half": False}] * 8 + [{"excused": False, "half": True}, {"excused": True, "half": False}]
    t = absence_totals(rows)
    assert t == {"unexcused": 8.5, "excused": 1.0, "total": 9.5}
    status = absence_status(t)
    assert "Özürsüz 8,5/10" in status and "⚠️" in status
    assert "⚠️" not in absence_status(absence_totals([{"excused": False, "half": False}]))


def test_parse_exam():
    assert parse_exam_result({"kind": "tyt", "total": 78.5, "details": {}}) == ("TYT", 78.5, {})
    assert parse_exam_result({"kind": "TYT", "total": None, "details": {"Türkçe": 32, "Matematik": 28.25}}) == ("TYT", 60.25, {"Türkçe": 32.0, "Matematik": 28.25})
    with pytest.raises(NotThis):
        parse_exam_result({"kind": None})
    for bad in ({"kind": "TYT", "total": 130, "details": {}}, {"kind": "AYT", "total": 90, "details": {}}, {"kind": "LGS", "total": 50, "details": {}}, {"kind": "TYT", "total": None, "details": {}}):
        with pytest.raises(SchoolError):
            parse_exam_result(bad)


def test_exam_summary_with_target():
    exams = [{"kind": "TYT", "total": t, "taken": date(2026, 10, d)} for t, d in ((60, 1), (70, 5), (80, 9), (90, 12))]
    text = exam_summary(exams, "TYT", 95)
    assert "Son deneme: 90 net" in text and "Son 3 ortalama: 80 net" in text and "Hedefe 15 net var" in text
    assert exam_summary([], "TYT", 95) is None
    assert "Hedefe" not in exam_summary(exams, "TYT", None)
    assert "Hedefin üzerindesin" in exam_summary(exams, "TYT", 70)
