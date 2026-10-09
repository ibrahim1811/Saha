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
