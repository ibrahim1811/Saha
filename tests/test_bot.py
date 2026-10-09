from types import SimpleNamespace

import pytest
from telegram.ext import ApplicationHandlerStop

from app.bot import gate


def _ctx():
    return SimpleNamespace(bot_data={"cfg": SimpleNamespace(owner_id=42)})


async def test_gate_allows_owner():
    assert await gate(SimpleNamespace(effective_user=SimpleNamespace(id=42)), _ctx()) is None


@pytest.mark.parametrize("user", [SimpleNamespace(id=7), None])
async def test_gate_blocks_others(user):
    with pytest.raises(ApplicationHandlerStop):
        await gate(SimpleNamespace(effective_user=user), _ctx())


from unittest.mock import AsyncMock

from telegram.error import Conflict

from app import bot as botmod
from app.llm import LLMError
from tests.fakes import FakeLLM
from zoneinfo import ZoneInfo


def _msg_update(text):
    message = SimpleNamespace(text=text, reply_text=AsyncMock())
    return SimpleNamespace(message=message, effective_chat=SimpleNamespace(id=42))


def _msg_ctx(llm):
    cfg = SimpleNamespace(owner_id=42, tz=ZoneInfo("Europe/Istanbul"))
    return SimpleNamespace(
        bot_data={"cfg": cfg, "llm": llm, "db": SimpleNamespace()},
        bot=SimpleNamespace(send_chat_action=AsyncMock(), send_message=AsyncMock()),
        job_queue=SimpleNamespace(),
        error=None,
    )


async def test_reminder_llm_failure_replies_turkish():
    update = _msg_update("yarın faturayı hatırlat")
    await botmod.text(update, _msg_ctx(FakeLLM(exc=LLMError("LLM API hatası 500"))))
    reply = update.message.reply_text.await_args.args[0]
    assert "şu an" in reply and "500" not in reply


async def test_chat_llm_failure_replies_turkish():
    update = _msg_update("bugün ne var?")
    ctx = _msg_ctx(FakeLLM(exc=LLMError("boom")))
    ctx.bot_data["db"] = SimpleNamespace(recent_notes=AsyncMock(return_value=[]), all_schedules=AsyncMock(return_value={}))
    await botmod.text(update, ctx)
    assert "şu an" in update.message.reply_text.await_args.args[0]


async def test_on_error_ignores_polling_conflict():
    ctx = _msg_ctx(None)
    ctx.error = Conflict("terminated by other getUpdates request")
    await botmod.on_error(None, ctx)
    ctx.bot.send_message.assert_not_awaited()


from datetime import time

from telegram.ext import Application

from app import briefing as briefing_mod
from app import card as card_mod
from app.briefing import Briefing, WeatherInfo
from app.weather import DayWeather

TZ = ZoneInfo("Europe/Istanbul")
INFO = WeatherInfo(DayWeather(11, 27, 12, 22, 0, 10), "İnce ceket al.", ["ceket al"])
RESULT = Briefing(header="Günaydın", text="Günaydın\n\n🌤 Hava\nx\n\n📚 Dersler", text_without_weather="Günaydın\n\n📚 Dersler", weather=INFO)


def _brief_ctx():
    cfg = SimpleNamespace(owner_id=42, tz=TZ, briefing_time=time(7, 0, tzinfo=TZ))
    return SimpleNamespace(
        bot_data={"cfg": cfg, "llm": None, "http": None, "db": SimpleNamespace(get_settings=AsyncMock(return_value=None))},
        bot=SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock()),
    )


def _patch_build(monkeypatch, result=RESULT):
    async def fake_build(today, src, settings):
        return result
    monkeypatch.setattr(briefing_mod, "make_sources", lambda *a, **k: None)
    monkeypatch.setattr(briefing_mod, "build", fake_build)


async def test_send_briefing_with_photo_card(monkeypatch):
    _patch_build(monkeypatch)
    ctx = _brief_ctx()
    await botmod.send_briefing(ctx)
    ctx.bot.send_photo.assert_awaited_once()
    assert "👕 İnce ceket al." in ctx.bot.send_photo.await_args.kwargs["caption"]
    assert ctx.bot.send_message.await_args.args[1] == "Günaydın\n\n📚 Dersler"


async def test_send_briefing_card_error_falls_back_to_text(monkeypatch):
    _patch_build(monkeypatch)
    monkeypatch.setattr(card_mod, "render_card", lambda *a: (_ for _ in ()).throw(OSError("font yok")))
    ctx = _brief_ctx()
    await botmod.send_briefing(ctx)
    ctx.bot.send_photo.assert_not_awaited()
    assert ctx.bot.send_message.await_args.args[1] == RESULT.text


async def test_send_briefing_photo_disabled(monkeypatch):
    _patch_build(monkeypatch)
    ctx = _brief_ctx()
    ctx.bot_data["db"].get_settings = AsyncMock(return_value={"photo_card": False})
    await botmod.send_briefing(ctx)
    ctx.bot.send_photo.assert_not_awaited()
    assert ctx.bot.send_message.await_args.args[1] == RESULT.text


def test_reschedule_replaces_job():
    app = Application.builder().token("123:abc").build()
    botmod.reschedule_briefing(app.job_queue, "07:00", TZ)
    botmod.reschedule_briefing(app.job_queue, "08:15", TZ)
    jobs = app.job_queue.get_jobs_by_name("sabah-ozeti")
    assert len(jobs) == 1 and jobs[0].data == "08:15"


async def test_panel_command_sends_webapp_button():
    update = _msg_update("/panel")
    ctx = _msg_ctx(None)
    ctx.bot_data["cfg"].public_url = "https://saha.onrender.com"
    await botmod.panel(update, ctx)
    markup = update.message.reply_text.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].web_app.url == "https://saha.onrender.com/"


async def test_panel_command_without_url():
    update = _msg_update("/panel")
    ctx = _msg_ctx(None)
    ctx.bot_data["cfg"].public_url = None
    await botmod.panel(update, ctx)
    assert "adres" in update.message.reply_text.await_args.args[0]


def _query_update(data, message_id=100):
    query = SimpleNamespace(data=data, answer=AsyncMock(), edit_message_text=AsyncMock(), message=SimpleNamespace(message_id=message_id))
    return SimpleNamespace(callback_query=query)


def _photo_ctx(existing, parsed, kind=("dershane", "cumartesi")):
    db = SimpleNamespace(get_schedule=AsyncMock(return_value=existing), save_schedule=AsyncMock())
    return SimpleNamespace(
        user_data={"pending": {100: {"photo": b"img", "kind": kind, "parsed": parsed}}},
        bot_data={"cfg": SimpleNamespace(owner_id=42, tz=TZ), "db": db, "llm": FakeLLM(reply=json.dumps(parsed))},
    )


import json

FIRST = [{"saat": "13:30-15:10", "ders": "TYT Mat"}]
SECOND = [{"saat": "15:50-17:20", "ders": "TYT Fizik"}]


async def test_preview_offers_merge_when_schedule_exists():
    ctx = _photo_ctx(FIRST, SECOND)
    update = _query_update("kind:dershane:cumartesi")
    await botmod.on_button(update, ctx)
    markup = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
    datas = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "merge" in datas and "save" in datas


async def test_preview_without_existing_offers_plain_save():
    ctx = _photo_ctx(None, SECOND)
    update = _query_update("kind:dershane:cumartesi")
    await botmod.on_button(update, ctx)
    markup = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
    assert "merge" not in [b.callback_data for row in markup.inline_keyboard for b in row]


async def test_merge_button_saves_sorted_union():
    ctx = _photo_ctx(SECOND, FIRST)
    update = _query_update("merge")
    await botmod.on_button(update, ctx)
    saved = ctx.bot_data["db"].save_schedule.await_args.args
    assert saved[:2] == ("dershane", "cumartesi")
    assert [l["ders"] for l in saved[2]] == ["TYT Mat", "TYT Fizik"]
    assert "TYT Mat" in update.callback_query.edit_message_text.await_args.args[0]



class _File:
    def __init__(self, data):
        self.data = data

    async def download_as_bytearray(self):
        return bytearray(self.data)


def _photo_update(data, reply_id):
    size = SimpleNamespace(get_file=AsyncMock(return_value=_File(data)))
    message = SimpleNamespace(photo=[size], reply_text=AsyncMock(return_value=SimpleNamespace(message_id=reply_id)))
    return SimpleNamespace(message=message)


async def test_two_photos_each_button_reads_its_own_photo():
    llm = FakeLLM(reply=json.dumps(FIRST))
    db = SimpleNamespace(get_schedule=AsyncMock(return_value=None), save_schedule=AsyncMock())
    ctx = SimpleNamespace(user_data={}, bot_data={"cfg": SimpleNamespace(owner_id=42, tz=TZ), "db": db, "llm": llm})
    await botmod.photo(_photo_update(b"birinci", 201), ctx)
    await botmod.photo(_photo_update(b"ikinci", 202), ctx)
    await botmod.on_button(_query_update("kind:dershane:cumartesi", 201), ctx)
    assert llm.calls[-1]["image"] == b"birinci"
    await botmod.on_button(_query_update("kind:dershane:cumartesi", 202), ctx)
    assert llm.calls[-1]["image"] == b"ikinci"
    await botmod.on_button(_query_update("save", 201), ctx)
    assert 201 not in ctx.user_data["pending"] and 202 in ctx.user_data["pending"]


async def test_button_on_unknown_message_asks_to_resend():
    ctx = SimpleNamespace(user_data={}, bot_data={})
    update = _query_update("save", 999)
    await botmod.on_button(update, ctx)
    assert "tekrar" in update.callback_query.edit_message_text.await_args.args[0]


async def test_pending_photos_capped():
    ctx = SimpleNamespace(user_data={}, bot_data={})
    for i in range(botmod.MAX_PENDING_PHOTOS + 3):
        await botmod.photo(_photo_update(b"x", 300 + i), ctx)
    pending = ctx.user_data["pending"]
    assert len(pending) == botmod.MAX_PENDING_PHOTOS and 300 not in pending and 312 in pending
