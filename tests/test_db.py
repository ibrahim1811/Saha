import os
from datetime import datetime, timedelta, timezone

import pytest

from app.db import DB

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL yok")


@pytest.fixture
async def db():
    d = await DB.connect(URL)
    await d.pool.execute("TRUNCATE schedules, notes, reminders RESTART IDENTITY")
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
