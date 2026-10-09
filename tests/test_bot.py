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
    async def fake_build(today, src, settings, **kw):
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


from datetime import date, datetime as _dt, timedelta


@pytest.mark.parametrize("hour,minute,expected", [(6, 59, date(2026, 10, 9)), (7, 0, date(2026, 10, 10)), (22, 27, date(2026, 10, 10))])
def test_next_briefing_day(hour, minute, expected):
    assert botmod.next_briefing_day(_dt(2026, 10, 9, hour, minute, tzinfo=TZ), "07:00") == expected


async def test_send_briefing_uses_given_day(monkeypatch):
    asked = {}

    async def fake_build(bot_data, day, **kw):
        asked["day"] = day
        return RESULT, {"photo_card": False}

    monkeypatch.setattr(botmod, "build_briefing", fake_build)
    ctx = _brief_ctx()
    await botmod.send_briefing(ctx, date(2026, 10, 10))
    assert asked["day"] == date(2026, 10, 10)


async def test_scheduled_job_sends_today(monkeypatch):
    asked = {}

    async def fake_build(bot_data, day, **kw):
        asked["day"] = day
        return RESULT, {"photo_card": False}

    monkeypatch.setattr(botmod, "build_briefing", fake_build)
    await botmod.send_briefing(_brief_ctx())
    assert asked["day"] == _dt.now(TZ).date()


async def test_ozet_command_sends_next_briefing_day(monkeypatch):
    asked = {}

    async def fake_send(context, day=None):
        asked["day"] = day

    monkeypatch.setattr(botmod, "send_briefing", fake_send)
    monkeypatch.setattr(botmod, "_now", lambda context: _dt(2026, 10, 9, 22, 27, tzinfo=TZ))
    await botmod.ozet(SimpleNamespace(), _brief_ctx())
    assert asked["day"] == date(2026, 10, 10)


async def test_keepalive_pings_public_health():
    http = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(status_code=200)))
    cfg = SimpleNamespace(public_url="https://saha-q2hh.onrender.com")
    await botmod.keep_alive(SimpleNamespace(bot_data={"cfg": cfg, "http": http}))
    assert http.get.await_args.args[0] == "https://saha-q2hh.onrender.com/health"


async def test_keepalive_failure_is_logged_not_raised(caplog):
    http = SimpleNamespace(get=AsyncMock(side_effect=RuntimeError("down")))
    cfg = SimpleNamespace(public_url="https://x")
    await botmod.keep_alive(SimpleNamespace(bot_data={"cfg": cfg, "http": http}))
    assert "down" in caplog.text


def test_keepalive_scheduled_only_with_public_url():
    app = Application.builder().token("123:abc").build()
    botmod.schedule_keep_alive(app.job_queue, None)
    assert app.job_queue.get_jobs_by_name("uyanik-tut") == ()
    botmod.schedule_keep_alive(app.job_queue, "https://x")
    assert len(app.job_queue.get_jobs_by_name("uyanik-tut")) == 1


@pytest.mark.parametrize("text,is_reminder", [
    ("yarın 15'te faturayı hatırlat", True),
    ("YARIN FATURAYI HATIRLAT", True),
    ("Hatırlat bana su içmeyi", True),
    ("neyi hatırlatmıştım?", False),
    ("bugün ne var", False),
])
def test_reminder_intent(text, is_reminder):
    assert botmod.is_reminder_request(text) is is_reminder


async def test_photo_timeout_does_not_resend_weather(monkeypatch):
    from telegram.error import TimedOut

    _patch_build(monkeypatch)
    ctx = _brief_ctx()
    ctx.bot.send_photo = AsyncMock(side_effect=TimedOut())
    await botmod.send_briefing(ctx)
    assert ctx.bot.send_message.await_args.args[1] == RESULT.text_without_weather


def test_evening_job_scheduling():
    app = Application.builder().token("123:abc").build()
    botmod.reschedule_evening(app.job_queue, {"evening_enabled": True, "evening_time": "23:00"}, TZ)
    botmod.reschedule_evening(app.job_queue, {"evening_enabled": True, "evening_time": "22:30"}, TZ)
    jobs = app.job_queue.get_jobs_by_name("aksam-ozeti")
    assert len(jobs) == 1 and jobs[0].data == "22:30"
    botmod.reschedule_evening(app.job_queue, {"evening_enabled": False, "evening_time": "22:30"}, TZ)
    assert app.job_queue.get_jobs_by_name("aksam-ozeti") == ()


async def test_evening_job_sends_tomorrow_evening_mode(monkeypatch):
    asked = {}

    async def fake_send(context, day=None, evening=False):
        asked.update(day=day, evening=evening)

    monkeypatch.setattr(botmod, "send_briefing", fake_send)
    monkeypatch.setattr(botmod, "_now", lambda context: _dt(2026, 10, 9, 23, 0, tzinfo=TZ))
    await botmod.send_evening(_brief_ctx())
    assert asked == {"day": date(2026, 10, 10), "evening": True}


async def test_text_routes_task_request():
    from datetime import timedelta as _td

    due = (_dt.now(TZ) + _td(days=2)).date()
    llm = FakeLLM(reply=f'{{"kind": "odev", "title": "Fizik ödevi", "due": "{due.isoformat()}"}}')
    update = _msg_update("fizik ödevi cuma teslim")
    ctx = _msg_ctx(llm)
    ctx.bot_data["db"] = SimpleNamespace(add_task=AsyncMock(return_value=7))
    await botmod.text(update, ctx)
    ctx.bot_data["db"].add_task.assert_awaited_once_with("odev", "Fizik ödevi", due)
    assert "#7" in update.message.reply_text.await_args.args[0]


async def test_bitti_marks_done():
    update = _msg_update("/bitti 7")
    ctx = _msg_ctx(None)
    ctx.args = ["7"]
    ctx.bot_data["db"] = SimpleNamespace(set_task_done=AsyncMock(return_value=True))
    await botmod.bitti(update, ctx)
    ctx.bot_data["db"].set_task_done.assert_awaited_once_with(7, True)


async def test_text_task_cue_but_not_a_task_goes_to_chat():
    llm = FakeLLM(reply='{"kind": null}')
    update = _msg_update("yarın sınavım var mı")
    ctx = _msg_ctx(llm)
    ctx.bot_data["db"] = SimpleNamespace(add_task=AsyncMock(), recent_notes=AsyncMock(return_value=[]), all_schedules=AsyncMock(return_value={}))
    await botmod.text(update, ctx)
    ctx.bot_data["db"].add_task.assert_not_awaited()
    assert len(llm.calls) == 2


@pytest.mark.parametrize("arg", ["²", "-1", "abc", "1.5"])
async def test_bitti_rejects_bad_numbers(arg):
    update = _msg_update("/bitti")
    ctx = _msg_ctx(None)
    ctx.args = [arg]
    ctx.bot_data["db"] = SimpleNamespace(set_task_done=AsyncMock())
    await botmod.bitti(update, ctx)
    ctx.bot_data["db"].set_task_done.assert_not_awaited()
    assert "Kullanım" in update.message.reply_text.await_args.args[0]


async def test_sil_rejects_superscript():
    update = _msg_update("/sil")
    ctx = _msg_ctx(None)
    ctx.args = ["²"]
    await botmod.sil(update, ctx)
    assert "Kullanım" in update.message.reply_text.await_args.args[0]


async def test_text_grade_saved():
    llm = FakeLLM(reply='{"subject": "Fizik", "label": "1. yazılı", "score": 85}')
    update = _msg_update("fizik 1. yazılı 85")
    ctx = _msg_ctx(llm)
    ctx.bot_data["db"] = SimpleNamespace(add_grade=AsyncMock(return_value=4))
    await botmod.text(update, ctx)
    ctx.bot_data["db"].add_grade.assert_awaited_once_with("Fizik", "1. yazılı", 85.0)
    assert "Fizik" in update.message.reply_text.await_args.args[0]


async def test_text_exam_saved_with_today():
    llm = FakeLLM(reply='{"kind": "TYT", "total": 78, "details": {}}')
    update = _msg_update("tyt deneme 78 net")
    ctx = _msg_ctx(llm)
    ctx.bot_data["db"] = SimpleNamespace(add_exam=AsyncMock(return_value=2), list_exams=AsyncMock(return_value=[]), get_settings=AsyncMock(return_value=None))
    ctx.bot_data["cfg"].briefing_time = time(7, 0, tzinfo=TZ)
    await botmod.text(update, ctx)
    args = ctx.bot_data["db"].add_exam.await_args.args
    assert args[:3] == ("TYT", 78.0, {}) and args[3] == _dt.now(TZ).date()


async def test_text_absence_saved():
    today = _dt.now(TZ).date()
    llm = FakeLLM(reply=f'{{"day": "{today.isoformat()}", "excused": false, "half": false}}')
    update = _msg_update("bugün okula gitmedim")
    ctx = _msg_ctx(llm)
    ctx.bot_data["db"] = SimpleNamespace(add_absence=AsyncMock(return_value=1), list_absences=AsyncMock(return_value=[{"excused": False, "half": False}]))
    await botmod.text(update, ctx)
    ctx.bot_data["db"].add_absence.assert_awaited_once_with(today, False, False)
    assert "Özürsüz 1/10" in update.message.reply_text.await_args.args[0]


async def test_voice_command_creates_task_instead_of_note():
    due = (_dt.now(TZ) + timedelta(days=2)).date()
    llm = FakeLLM(reply=f'{{"kind": "odev", "title": "Fizik ödevi", "due": "{due.isoformat()}"}}')
    update = _msg_update(None)
    update.message.voice = SimpleNamespace(get_file=AsyncMock(return_value=_File(b"ogg")))
    ctx = _msg_ctx(llm)
    ctx.bot_data["transcriber"] = SimpleNamespace(transcribe=AsyncMock(return_value="fizik ödevi cuma teslim"))
    ctx.bot_data["db"] = SimpleNamespace(add_task=AsyncMock(return_value=9), add_note=AsyncMock())
    await botmod.voice(update, ctx)
    ctx.bot_data["db"].add_task.assert_awaited_once()
    ctx.bot_data["db"].add_note.assert_not_awaited()


async def test_voice_plain_still_saved_as_note():
    update = _msg_update(None)
    update.message.voice = SimpleNamespace(get_file=AsyncMock(return_value=_File(b"ogg")))
    ctx = _msg_ctx(FakeLLM())
    ctx.bot_data["transcriber"] = SimpleNamespace(transcribe=AsyncMock(return_value="süt almayı unutma"))
    ctx.bot_data["db"] = SimpleNamespace(add_note=AsyncMock())
    await botmod.voice(update, ctx)
    ctx.bot_data["db"].add_note.assert_awaited_once_with("süt almayı unutma", "ses")


async def test_photo_menu_first_asks_purpose():
    ctx = SimpleNamespace(user_data={}, bot_data={})
    upd = _photo_update(b"img", 500)
    await botmod.photo(upd, ctx)
    markup = upd.message.reply_text.await_args.kwargs["reply_markup"]
    assert [b.callback_data for row in markup.inline_keyboard for b in row] == ["pick:program", "pick:note", "pick:solve"]


async def test_pick_program_shows_kind_buttons():
    ctx = SimpleNamespace(user_data={"pending": {500: {"photo": b"img"}}}, bot_data={})
    update = _query_update("pick:program", 500)
    await botmod.on_button(update, ctx)
    markup = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "kind:okul:"


async def test_solve_flow_uses_vision_then_text_model():
    llm = FakeLLM(reply="Soru: 2+2=? A) 3 B) 4")
    db = SimpleNamespace()
    ctx = SimpleNamespace(user_data={"pending": {500: {"photo": b"img"}}}, bot_data={"llm": llm, "db": db, "cfg": SimpleNamespace(owner_id=42, tz=TZ)}, bot=SimpleNamespace(send_message=AsyncMock()))
    update = _query_update("pick:solve", 500)
    update.effective_chat = SimpleNamespace(id=42)
    await botmod.on_button(update, ctx)
    assert llm.calls[0]["image"] == b"img" and llm.calls[1]["image"] is None
    assert "2+2" in llm.calls[1]["prompt"]
    assert 500 not in ctx.user_data["pending"]


async def test_note_flow_saves_with_subject():
    llm = FakeLLM(reply="Newton'un 2. yasası F = m·a")
    db = SimpleNamespace(get_schedule=AsyncMock(return_value={"pazartesi": [{"saat": "", "ders": "Fizik"}, {"saat": "", "ders": "Kimya"}]}), add_note=AsyncMock(return_value=3))
    ctx = SimpleNamespace(user_data={"pending": {500: {"photo": b"img"}}}, bot_data={"llm": llm, "db": db, "cfg": SimpleNamespace(owner_id=42, tz=TZ)})
    update = _query_update("pick:note", 500)
    await botmod.on_button(update, ctx)
    markup = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
    labels = [b.text for row in markup.inline_keyboard for b in row]
    assert "Fizik" in labels and "Kimya" in labels and "Diğer" in labels
    fizik = [b.callback_data for row in markup.inline_keyboard for b in row if b.text == "Fizik"][0]
    await botmod.on_button(_query_update(fizik, 500), ctx)
    db.add_note.assert_awaited_once_with("Newton'un 2. yasası F = m·a", "foto", "Fizik")


async def test_yks_command():
    update = _msg_update("/yks")
    ctx = _msg_ctx(None)
    ctx.bot_data["cfg"].briefing_time = time(7, 0, tzinfo=TZ)
    ctx.bot_data["db"] = SimpleNamespace(get_settings=AsyncMock(return_value=None), list_exams=AsyncMock(return_value=[]))
    await botmod.yks(update, ctx)
    assert "YKS" in ctx.bot.send_message.await_args.args[1]
