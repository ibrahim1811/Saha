from datetime import date

import pytest

from app import examcal

TODAY = date(2026, 11, 2)


def _exam(subject="Matematik", day=date(2026, 11, 10), at_time="09:40", kind="yazılı", branch=""):
    return {"subject": subject, "day": day, "at_time": at_time, "kind": kind, "branch": branch}


def test_parse_result_keeps_branches_and_normalizes():
    data = {
        "siniflar": ["12 Say", "12 EA"],
        "sinavlar": [
            {"sinif": "12 Say", "tarih": "2026-11-10", "saat": "9.40", "ders": "Matematik", "tur": "Yazılı"},
            {"sinif": "", "tarih": "2026-11-12", "saat": "", "ders": "Türkçe", "tur": ""},
        ],
    }
    branches, exams = examcal.parse_result(data, TODAY)
    assert branches == ["12 Say", "12 EA"]
    assert exams[0]["at_time"] == "09:40" and exams[0]["kind"] == "yazılı"
    assert exams[1]["at_time"] == "" and exams[1]["kind"] == "yazılı" and exams[1]["branch"] == ""


def test_parse_result_accepts_plain_list_and_derives_branches():
    branches, exams = examcal.parse_result([{"ders": "Fizik", "tarih": "10.11", "sinif": "11-B"}], TODAY)
    assert branches == ["11-B"]
    assert exams[0]["day"] == date(2026, 11, 10)


@pytest.mark.parametrize("data", [{"sinavlar": []}, {"sinavlar": [{"ders": "  ", "tarih": "2026-11-10"}]}, "x"])
def test_parse_result_rejects_empty_or_broken(data):
    with pytest.raises(examcal.ExamCalError):
        examcal.parse_result(data, TODAY)


def test_parse_result_rejects_bad_date():
    with pytest.raises(examcal.ExamCalError):
        examcal.parse_result({"sinavlar": [{"ders": "Fizik", "tarih": "çok yakında"}]}, TODAY)


def test_yearless_date_rolls_forward_when_long_past():
    _, exams = examcal.parse_result({"sinavlar": [{"ders": "Fizik", "tarih": "2026-03-10"}]}, TODAY)
    assert exams[0]["day"] == date(2027, 3, 10)


def test_filter_branch_keeps_common_exams():
    exams = [_exam(branch="12 Say"), _exam(subject="Türkçe", branch=""), _exam(subject="Fizik", branch="12 EA")]
    assert [e["subject"] for e in examcal.filter_branch(exams, "12 Say")] == ["Matematik", "Türkçe"]
    assert len(examcal.filter_branch(exams, None)) == 3


def test_future_only_drops_old_exams():
    exams = [_exam(day=date(2026, 10, 1)), _exam(subject="Fizik", day=date(2026, 11, 2))]
    assert [e["subject"] for e in examcal.future_only(exams, TODAY)] == ["Fizik"]


def test_plan_add_skips_duplicates_and_sorts():
    existing = [_exam()]
    new = [_exam(), _exam(subject="Fizik", day=date(2026, 11, 5), at_time=""), _exam(subject="Türkçe", day=date(2026, 11, 5), at_time="09:00")]
    added = examcal.plan_add(existing, new)
    assert [e["subject"] for e in added] == ["Türkçe", "Fizik"]


def test_merge_keeps_ids_of_existing():
    existing = [{**_exam(), "id": 7}]
    merged = examcal.merge(existing, [_exam(), _exam(subject="Fizik", day=date(2026, 11, 5))])
    assert [e.get("id") for e in merged] == [None, 7]


@pytest.mark.parametrize("diff,text", [(0, "bugün"), (1, "yarın"), (3, "3 gün sonra"), (-2, "2 gün önce")])
def test_relative(diff, text):
    from datetime import timedelta

    assert examcal.relative(TODAY + timedelta(days=diff), TODAY) == text


def test_format_upcoming_only_next_two_weeks_with_countdown():
    exams = [_exam(), _exam(subject="Fizik", day=date(2026, 12, 20))]
    out = examcal.format_upcoming(exams, TODAY)
    assert "8 gün sonra" in out and "Matematik yazılısı" in out
    assert "Fizik" not in out
    assert examcal.format_upcoming([], TODAY) == "Yaklaşan sınav yok 🎉"


def test_format_exam_has_id_and_branch():
    line = examcal.format_exam({**_exam(branch="12 Say"), "id": 4}, TODAY)
    assert "#4" in line and "12 Say" in line and "8 gün sonra" in line


def test_format_all_separates_upcoming_and_past():
    exams = [{**_exam(), "id": 1}, {**_exam(subject="Eski", day=date(2026, 10, 20)), "id": 2}]
    out = examcal.format_all(exams, TODAY)
    assert "Yaklaşan sınavlar" in out and "Geçmiş" in out and "Eski" in out


async def test_parse_text_result_and_not_an_exam():
    exam = examcal.parse_text_result({"ders": "Matematik", "tarih": "2026-11-10", "saat": "09:40"}, TODAY)
    assert exam["subject"] == "Matematik" and exam["day"] == date(2026, 11, 10)
    with pytest.raises(examcal.NotAnExam):
        examcal.parse_text_result({"ders": None}, TODAY)
