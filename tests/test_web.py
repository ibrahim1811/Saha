import time as _time
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.status import ErrorBuffer
from app.web import build_web_app
from app.webauth import sign_init_data
from tests.fakes import FakeLLM

TOKEN = "123:abc"
TZ = ZoneInfo("Europe/Istanbul")


class Store:
    def __init__(self):
        self.settings = None
        self.schedules = {}
        self.notes = [{"id": 1, "text": "Süt al", "source": "ses", "created_at": datetime(2026, 10, 9, 10, tzinfo=timezone.utc)}]
        self.reminders = {}

    async def get_settings(self):
        return self.settings

    async def save_settings(self, value):
        self.settings = value

    async def all_schedules(self):
        return {"okul": self.schedules.get(("okul", "")), "cumartesi": self.schedules.get(("dershane", "cumartesi")),
                "pazar": self.schedules.get(("dershane", "pazar"))}

    async def save_schedule(self, kind, day, data):
        self.schedules[(kind, day)] = data

    async def delete_schedule(self, kind, day=""):
        return self.schedules.pop((kind, day), None) is not None

    async def search_notes(self, q, limit=100):
        return [n for n in self.notes if q.lower() in n["text"].lower()]

    async def delete_note(self, note_id):
        before = len(self.notes)
        self.notes = [n for n in self.notes if n["id"] != note_id]
        return len(self.notes) < before

    async def pending_reminders(self):
        return [{"id": k, **v} for k, v in self.reminders.items()]

    async def add_reminder(self, text, due_at):
        rid = len(self.reminders) + 1
        self.reminders[rid] = {"text": text, "due_at": due_at}
        return rid

    async def delete_reminder(self, rid):
        return self.reminders.pop(rid, None) is not None


def _tg(llm=None):
    cfg = SimpleNamespace(owner_id=42, tz=TZ, telegram_token=TOKEN, briefing_time=time(7, 0, tzinfo=TZ))
    jq = MagicMock()
    jq.get_jobs_by_name.return_value = []
    return SimpleNamespace(
        bot_data={"cfg": cfg, "db": Store(), "llm": llm or FakeLLM(), "http": None, "errors": ErrorBuffer()},
        job_queue=jq,
        bot=SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock()),
    )


def _auth(user_id=42):
    return {"Authorization": "tma " + sign_init_data({"id": user_id}, TOKEN, int(_time.time()))}


@pytest.fixture
async def client():
    tg = _tg()
    async with TestClient(TestServer(build_web_app(tg))) as c:
        c.tg = tg
        yield c


async def test_health_and_index_public(client):
    assert await (await client.get("/health")).text() == "ok"
    resp = await client.get("/")
    assert resp.status == 200 and "telegram-web-app.js" in await resp.text()


async def test_api_requires_auth(client):
    assert (await client.get("/api/settings")).status == 401
    assert (await client.get("/api/settings", headers={"Authorization": "tma hash=x&auth_date=1"})).status == 401
    assert (await client.get("/api/settings", headers=_auth(7))).status == 403


async def test_settings_get_put(client):
    s = await (await client.get("/api/settings", headers=_auth())).json()
    assert s["briefing_time"] == "07:00"
    s["briefing_time"] = "06:30"
    s["sections"]["news"] = False
    resp = await client.put("/api/settings", json=s, headers=_auth())
    assert resp.status == 200
    assert client.tg.bot_data["db"].settings["briefing_time"] == "06:30"
    client.tg.job_queue.run_daily.assert_called_once()


async def test_settings_invalid_400_not_saved(client):
    s = await (await client.get("/api/settings", headers=_auth())).json()
    s["news_count"] = 0
    resp = await client.put("/api/settings", json=s, headers=_auth())
    assert resp.status == 400 and "Haber sayısı" in (await resp.json())["error"]
    assert client.tg.bot_data["db"].settings is None


async def test_schedule_put_validates(client):
    ok = await client.put("/api/schedules/dershane/cumartesi", json=[{"saat": "10:00", "ders": "Fizik"}], headers=_auth())
    assert ok.status == 200
    bad = await client.put("/api/schedules/dershane/pazar", json=[{"saat": "10:00", "ders": " "}], headers=_auth())
    assert bad.status == 400
    assert (await client.put("/api/schedules/dershane/sali", json=[], headers=_auth())).status == 404
    data = await (await client.get("/api/schedules", headers=_auth())).json()
    assert data["cumartesi"][0]["ders"] == "Fizik" and data["pazar"] is None
    assert (await client.delete("/api/schedules/dershane/cumartesi", headers=_auth())).status == 200


async def test_notes_search_and_delete(client):
    notes = await (await client.get("/api/notes?q=süt", headers=_auth())).json()
    assert notes[0]["text"] == "Süt al" and notes[0]["created_at"].startswith("2026-10-09")
    assert (await client.delete("/api/notes/1", headers=_auth())).status == 200
    assert (await client.delete("/api/notes/1", headers=_auth())).status == 404


async def test_reminder_create_list_delete():
    when = (datetime.now(TZ) + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
    tg = _tg(FakeLLM(reply=f'{{"when": "{when:%Y-%m-%dT%H:%M}", "text": "fatura"}}'))
    async with TestClient(TestServer(build_web_app(tg))) as c:
        resp = await c.post("/api/reminders", json={"text": "yarın 15'te fatura"}, headers=_auth())
        assert resp.status == 200 and (await resp.json())["text"] == "fatura"
        tg.job_queue.run_once.assert_called_once()
        items = await (await c.get("/api/reminders", headers=_auth())).json()
        assert items[0]["text"] == "fatura"
        assert (await c.delete(f"/api/reminders/{items[0]['id']}", headers=_auth())).status == 200


async def test_reminder_past_400():
    tg = _tg(FakeLLM(reply='{"when": "2020-01-01T10:00", "text": "x"}'))
    async with TestClient(TestServer(build_web_app(tg))) as c:
        resp = await c.post("/api/reminders", json={"text": "geçmiş"}, headers=_auth())
        assert resp.status == 400 and "geçmişte" in (await resp.json())["error"]


async def test_status(client):
    data = await (await client.get("/api/status", headers=_auth())).json()
    assert data["settings"]["briefing_time"] == "07:00"
    assert data["errors"] == [] and data["next_briefing"] is None and data["uptime_s"] >= 0


async def test_weather_endpoint(monkeypatch):
    from app import weather as weather_mod
    from app.weather import DayWeather

    async def fake_fetch(lat, lon, tz, http):
        return DayWeather(11, 27, 12, 22, 10, 9, tuple([20.0] * 24), "clear")

    monkeypatch.setattr(weather_mod, "fetch", fake_fetch)
    tg = _tg()
    tg.bot_data["cfg"].lat, tg.bot_data["cfg"].lon = 38.39, 27.17
    async with TestClient(TestServer(build_web_app(tg))) as c:
        data = await (await c.get("/api/weather", headers=_auth())).json()
        assert data["condition"] == "clear" and data["label"] == "Açık" and data["t_max"] == 27 and len(data["hourly"]) == 24
