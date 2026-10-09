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
