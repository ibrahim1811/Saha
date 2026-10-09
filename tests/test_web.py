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
    names = [c.kwargs["name"] for c in client.tg.job_queue.run_daily.call_args_list]
    assert names == ["sabah-ozeti", "aksam-ozeti"]


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

    async def fake_fetch(lat, lon, tz, http, day=None):
        return DayWeather(11, 27, 12, 22, 10, 9, tuple([20.0] * 24), "clear")

    monkeypatch.setattr(weather_mod, "fetch", fake_fetch)
    tg = _tg()
    tg.bot_data["cfg"].lat, tg.bot_data["cfg"].lon = 38.39, 27.17
    async with TestClient(TestServer(build_web_app(tg))) as c:
        data = await (await c.get("/api/weather", headers=_auth())).json()
        assert data["condition"] == "clear" and data["label"] == "Açık" and data["t_max"] == 27 and len(data["hourly"]) == 24


@pytest.mark.parametrize("hour,expect_tomorrow", [(9, False), (18, True), (22, True)])
async def test_weather_shows_tomorrow_in_evening(monkeypatch, hour, expect_tomorrow):
    from app import web as web_mod
    from app import weather as weather_mod
    from app.weather import DayWeather

    asked = {}

    async def fake_fetch(lat, lon, tz, http, day=None):
        asked["day"] = day
        return DayWeather(15, 29, 16, 24, 10, 12, tuple([20.0] * 24), "partly")

    monkeypatch.setattr(weather_mod, "fetch", fake_fetch)
    monkeypatch.setattr(web_mod, "_now", lambda tz: datetime(2026, 10, 9, hour, 17, tzinfo=tz))
    tg = _tg()
    tg.bot_data["cfg"].lat, tg.bot_data["cfg"].lon = 38.39, 27.17
    async with TestClient(TestServer(build_web_app(tg))) as c:
        data = await (await c.get("/api/weather", headers=_auth())).json()
    assert data["is_tomorrow"] is expect_tomorrow
    assert asked["day"].isoformat() == ("2026-10-10" if expect_tomorrow else "2026-10-09")
    assert data["day"] == asked["day"].isoformat()


@pytest.mark.parametrize("hour,expected", [(6, "2026-10-09"), (22, "2026-10-10")])
async def test_preview_targets_next_briefing_day(monkeypatch, hour, expected):
    from app import bot as bot_mod
    from app import web as web_mod
    from app.briefing import Briefing

    asked = {}

    async def fake_build(bot_data, day, **kw):
        asked["day"] = day
        return Briefing("h", "metin", "metin", None), {"photo_card": True}

    monkeypatch.setattr(bot_mod, "build_briefing", fake_build)
    monkeypatch.setattr(web_mod, "_now", lambda tz: datetime(2026, 10, 9, hour, 0, tzinfo=tz))
    async with TestClient(TestServer(build_web_app(_tg()))) as c:
        data = await (await c.get("/api/briefing/preview", headers=_auth())).json()
    assert asked["day"].isoformat() == expected and data["text"] == "metin"


async def test_send_now_sends_next_briefing_day(monkeypatch):
    from app import bot as bot_mod
    from app import web as web_mod

    asked = {}

    async def fake_send(context, day=None):
        asked["day"] = day

    monkeypatch.setattr(bot_mod, "send_briefing", fake_send)
    monkeypatch.setattr(web_mod, "_now", lambda tz: datetime(2026, 10, 9, 22, 27, tzinfo=tz))
    async with TestClient(TestServer(build_web_app(_tg()))) as c:
        assert (await c.post("/api/briefing/send", headers=_auth())).status == 200
    assert asked["day"].isoformat() == "2026-10-10"



class TaskStore(Store):
    def __init__(self):
        super().__init__()
        self.tasks = {}

    async def list_tasks(self, include_done=False):
        return [{"id": k, **v} for k, v in sorted(self.tasks.items()) if include_done or not v["done"]]

    async def add_task(self, kind, title, due):
        tid = len(self.tasks) + 1
        self.tasks[tid] = {"kind": kind, "title": title, "due": due, "done": False}
        return tid

    async def set_task_done(self, tid, done):
        if tid not in self.tasks:
            return False
        self.tasks[tid]["done"] = done
        return True

    async def delete_task(self, tid):
        return self.tasks.pop(tid, None) is not None


async def test_tasks_api_flow():
    due = (datetime.now(TZ) + timedelta(days=3)).date()
    tg = _tg(FakeLLM(reply=f'{{"kind": "sinav", "title": "Mat sınavı", "due": "{due.isoformat()}"}}'))
    tg.bot_data["db"] = TaskStore()
    async with TestClient(TestServer(build_web_app(tg))) as c:
        created = await (await c.post("/api/tasks", json={"text": "mat sınavı perşembe"}, headers=_auth())).json()
        assert created["title"] == "Mat sınavı" and created["due"] == due.isoformat()
        items = await (await c.get("/api/tasks", headers=_auth())).json()
        assert items[0]["label"] == "3 gün sonra"
        assert (await c.patch(f"/api/tasks/{created['id']}", json={"done": True}, headers=_auth())).status == 200
        assert await (await c.get("/api/tasks", headers=_auth())).json() == []
        assert len(await (await c.get("/api/tasks?all=1", headers=_auth())).json()) == 1
        assert (await c.patch("/api/tasks/99", json={"done": True}, headers=_auth())).status == 404
        assert (await c.patch(f"/api/tasks/{created['id']}", json={"done": "evet"}, headers=_auth())).status == 400
        assert (await c.delete(f"/api/tasks/{created['id']}", headers=_auth())).status == 200


async def test_task_past_date_400():
    tg = _tg(FakeLLM(reply='{"kind": "odev", "title": "x", "due": "2020-01-01"}'))
    tg.bot_data["db"] = TaskStore()
    async with TestClient(TestServer(build_web_app(tg))) as c:
        resp = await c.post("/api/tasks", json={"text": "eski ödev"}, headers=_auth())
        assert resp.status == 400 and "geçmişte" in (await resp.json())["error"]


async def test_static_not_cached(client):
    resp = await client.get("/static/app.js")
    assert resp.status == 200 and resp.headers["Cache-Control"] == "no-cache"


async def test_llm_down_returns_503():
    from app.llm import LLMError

    tg = _tg(FakeLLM(exc=LLMError("boom")))
    tg.bot_data["db"] = TaskStore()
    async with TestClient(TestServer(build_web_app(tg))) as c:
        resp = await c.post("/api/tasks", json={"text": "fizik ödevi cuma"}, headers=_auth())
        assert resp.status == 503 and "ulaşamıyorum" in (await resp.json())["error"]
