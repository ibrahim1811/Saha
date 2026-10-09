import os
from datetime import datetime, timedelta, timezone

import pytest

from app.db import DB

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL yok")


@pytest.fixture
async def db():
    d = await DB.connect(URL)
    await d.pool.execute("TRUNCATE schedules, notes, reminders, settings, tasks, grades, absences, exams RESTART IDENTITY")
    yield d
    await d.close()


async def test_schedule_upsert(db):
    await db.save_schedule("okul", "", {"pazartesi": [{"saat": "", "ders": "Mat"}]})
    await db.save_schedule("okul", "", {"pazartesi": [{"saat": "", "ders": "Fizik"}]})
    assert (await db.get_schedule("okul"))["pazartesi"][0]["ders"] == "Fizik"
    assert (await db.all_schedules())["cumartesi"] is None


async def test_notes_order(db):
    await db.add_note("ilk", "ses")
    await db.add_note("ikinci", "ses")
    assert [n["text"] for n in await db.recent_notes()] == ["ikinci", "ilk"]


async def test_reminders(db):
    due = datetime.now(timezone.utc) + timedelta(hours=1)
    rid = await db.add_reminder("fatura", due)
    assert [r["id"] for r in await db.pending_reminders()] == [rid]
    await db.mark_sent(rid)
    assert await db.pending_reminders() == []
    assert await db.delete_reminder(rid) is True
    assert await db.delete_reminder(rid) is False


async def test_settings_roundtrip(db):
    assert await db.get_settings() is None
    await db.save_settings({"briefing_time": "08:00"})
    await db.save_settings({"briefing_time": "09:00"})
    assert await db.get_settings() == {"briefing_time": "09:00"}


async def test_search_and_delete_notes(db):
    a = await db.add_note("Süt al", "ses")
    await db.add_note("Ahmet'i ara", "ses")
    assert [n["text"] for n in await db.search_notes("süt")] == ["Süt al"]
    assert len(await db.search_notes("")) == 2
    assert await db.delete_note(a) is True
    assert await db.delete_note(a) is False


async def test_delete_schedule(db):
    await db.save_schedule("dershane", "pazar", [{"saat": "", "ders": "Mat"}])
    assert await db.delete_schedule("dershane", "pazar") is True
    assert await db.get_schedule("dershane", "pazar") is None
    assert await db.delete_schedule("dershane", "pazar") is False


async def test_tasks_crud(db):
    from datetime import date

    a = await db.add_task("odev", "Fizik", date(2026, 10, 12))
    b = await db.add_task("sinav", "Mat", date(2026, 10, 10))
    assert [t["id"] for t in await db.list_tasks()] == [b, a]
    assert await db.set_task_done(b, True) is True
    assert [t["id"] for t in await db.list_tasks()] == [a]
    assert len(await db.list_tasks(include_done=True)) == 2
    assert [t["title"] for t in await db.tasks_due_between(date(2026, 10, 11), date(2026, 10, 15))] == ["Fizik"]
    assert await db.delete_task(a) is True and await db.delete_task(a) is False


async def test_upcoming_tasks_includes_overdue(db):
    from datetime import date

    await db.add_task("odev", "Eski", date(2026, 10, 1))
    await db.add_task("odev", "Uzak", date(2026, 12, 1))
    assert [t["title"] for t in await db.upcoming_tasks(date(2026, 10, 16))] == ["Eski"]


async def test_grades_crud(db):
    a = await db.add_grade("Fizik", "1. yazılı", 85)
    await db.add_grade("Kimya", "performans", 90.5)
    assert [(g["subject"], float(g["score"])) for g in await db.list_grades()] == [("Fizik", 85.0), ("Kimya", 90.5)]
    assert await db.delete_grade(a) is True and await db.delete_grade(a) is False


async def test_absences_upsert_by_day(db):
    from datetime import date

    await db.add_absence(date(2026, 10, 9), False, False)
    await db.add_absence(date(2026, 10, 9), True, True)
    rows = await db.list_absences()
    assert len(rows) == 1 and rows[0]["excused"] is True and rows[0]["half"] is True
    assert await db.delete_absence(rows[0]["id"]) is True


async def test_exams_crud(db):
    from datetime import date

    e = await db.add_exam("TYT", 78.5, {"Türkçe": 32}, date(2026, 10, 9))
    rows = await db.list_exams()
    assert rows[0]["kind"] == "TYT" and float(rows[0]["total"]) == 78.5 and rows[0]["details"] == {"Türkçe": 32}
    assert await db.delete_exam(e) is True


async def test_note_with_subject(db):
    await db.add_note("Newton yasaları", "foto", "Fizik")
    assert (await db.search_notes("newton"))[0]["subject"] == "Fizik"
