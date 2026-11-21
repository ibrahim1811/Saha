import copy
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from telegram.ext import ApplicationHandlerStop

from app import bot as botmod
from app import love, partner
from app.news import fetch
from app.settings import SettingsError

TZ = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 10, 11, 14, 0, tzinfo=TZ)


def test_invite_valid_and_expiry():
    inv = partner.new_invite(NOW)
    assert partner.invite_valid(inv, inv["code"], NOW)
    assert not partner.invite_valid(inv, "yanlis", NOW)
    assert not partner.invite_valid(inv, inv["code"], NOW + timedelta(hours=25))
    assert not partner.invite_valid(None, inv["code"], NOW)


def test_duration_and_quiet():
    assert partner.duration(NOW - timedelta(minutes=47), NOW) == "47 dakika"
    assert partner.duration(NOW - timedelta(hours=26, minutes=5), NOW) == "1 gün 2 saat 5 dakika"
    assert partner.duration(NOW, NOW) == "1 dakika"
    assert partner.is_quiet(NOW.replace(hour=3)) and not partner.is_quiet(NOW.replace(hour=8))


@pytest.mark.parametrize("msg,expected", [
    ("İlayda'ya yarın 15'te sınavını hatırlat", True),
    ("ilaydaya akşam ilacını hatırlat", True),
    ("yarın faturayı hatırlat", False),
    ("İlaydanın doğum gününü hatırlat", False),
])
def test_targets_partner(msg, expected):
    assert partner.targets_partner(msg, "İlayda") is expected


def test_validate_self():
    v = partner.validate_self({"briefing_time": "7:30", "evening_enabled": False, "news_topics": ["spor"]})
    assert v == {"briefing_time": "07:30", "evening_enabled": False, "news_topics": ["spor"]}
    with pytest.raises(SettingsError):
        partner.validate_self({"briefing_time": "07:00", "evening_enabled": True, "news_topics": ["yok"]})
    with pytest.raises(SettingsError):
        partner.validate_self({"briefing_time": "07:00", "evening_enabled": True, "news_topics": []})


def test_love_lines():
    rows = [
        {"name": "Biz", "day": date(2026, 3, 13), "yearly": True, "counter": True},
        {"name": "İlayda'nın doğum günü", "day": date(2008, 10, 14), "yearly": True, "counter": False},
        {"name": "Konser", "day": date(2026, 12, 1), "yearly": False, "counter": False},
    ]
    today = date(2026, 10, 11)
    assert love.lines(rows, today) == ["❤️ Biz: 213. gün", "📅 İlayda'nın doğum günü (18. yıl): 3 gün kaldı"]
    assert love.owner_alerts(rows, today) == ["⏳ 3 gün sonra İlayda'nın doğum günü! (14.10) Hazırlığını yaptın mı? 🎁"]
    assert love.lines(rows, date(2027, 3, 13))[:2] == ["❤️ Biz: 366. gün", "🎉 Bugün Biz! (1. yıl)"]


async def test_fetch_topics_interleaves_and_skips_failed():
    def handler(req):
        if "teknoloji" in str(req.url):
            return httpx.Response(200, text=_rss(["T1.", "T2.", "Ortak."]))
        if "bbc" in str(req.url):
            return httpx.Response(200, text=_rss(["G1.", "Ortak.", "G2."]))
        return httpx.Response(500)
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    text = await fetch(http, 5, ["teknoloji", "gundem", "spor"])
    assert text.split("\n") == ["• T1.", "• G1.", "• T2.", "• Ortak.", "• G2."]


def _rss(summaries):
    items = "".join(f"<item><title>b{i}</title><description>{s}</description></item>" for i, s in enumerate(summaries))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{items}</channel></rss>'


class KV:
    def __init__(self, **values):
        self.values = values

    async def get_kv(self, key):
        return self.values.get(key)

    async def set_kv(self, key, value):
        self.values[key] = value

    async def delete_kv(self, key):
        self.values.pop(key, None)


PARTNER = {"id": 99, "name": "İlayda", **partner.DEFAULTS}


def _ctx(db, p=PARTNER):
    jq = MagicMock()
    jq.get_jobs_by_name.return_value = []
    return SimpleNamespace(
        bot_data={"cfg": SimpleNamespace(owner_id=42, tz=TZ, public_url=None), "db": db, "partner": p},
        bot=SimpleNamespace(send_message=AsyncMock(), send_animation=AsyncMock(), username="SahaBot", set_my_commands=AsyncMock()),
        job_queue=jq,
    )


def _upd(user_id, text):
    msg = SimpleNamespace(text=text, reply_text=AsyncMock())
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id, first_name="İlayda"), message=msg, callback_query=None)


def _sent(mock, chat_id):
    return [c for c in mock.await_args_list if c.args[0] == chat_id]


async def test_kus_and_baris_flow():
    db = KV()
    ctx = _ctx(db)
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(_upd(99, partner.KUS), ctx)
    assert "kus" in db.values
    alarm = _sent(ctx.bot.send_animation, 42)[-1]
    assert "giphy.com" in alarm.args[1] and "BOYKOT BAŞLADI" in alarm.kwargs["caption"]
    assert alarm.kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "love:gonul"
    assert ctx.job_queue.run_repeating.call_args.kwargs["name"] == "kus-hatirlat"

    db.values["kus"] = {"since": (datetime.now(TZ) - timedelta(minutes=30)).isoformat()}
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(_upd(99, partner.BARIS), ctx)
    assert "kus" not in db.values and len(db.values["kus_log"]) == 1
    assert "barıştınız" in _sent(ctx.bot.send_animation, 42)[-1].kwargs["caption"]
    assert _sent(ctx.bot.send_animation, 99)


async def test_gif_failure_falls_back_to_text():
    ctx = _ctx(KV())
    ctx.bot.send_animation = AsyncMock(side_effect=Exception("bad gif"))
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(_upd(99, partner.OZLEDIM), ctx)
    assert _sent(ctx.bot.send_message, 42)[-1].args[1] == "🥺 İlayda seni özledi!"


async def test_ozledim_notifies_owner_with_gif():
    ctx = _ctx(KV())
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(_upd(99, partner.OZLEDIM), ctx)
    assert _sent(ctx.bot.send_animation, 42)[-1].kwargs["caption"] == "🥺 İlayda seni özledi!"


async def test_moral_alerts_owner_and_cheers_partner():
    ctx = _ctx(KV())
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(_upd(99, partner.MORAL), ctx)
    alert = _sent(ctx.bot.send_message, 42)[-1]
    assert "moralinin bozuk" in alert.args[1]
    assert alert.kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "love:moral"
    assert _sent(ctx.bot.send_animation, 99)


async def test_owner_gonul_needs_boykot():
    db = KV()
    ctx = _ctx(db)
    await botmod.owner_love_action(ctx, "gonul")
    assert "boykot yok" in ctx.bot.send_message.await_args.args[1]
    ctx.bot.send_animation.assert_not_awaited()
    db.values["kus"] = {"since": datetime.now(TZ).isoformat()}
    await botmod.owner_love_action(ctx, "gonul")
    gif = _sent(ctx.bot.send_animation, 99)[-1]
    assert "özür" in gif.kwargs["caption"]
    assert gif.kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "love:baris"


async def test_partner_inline_baris_button():
    db = KV(kus={"since": (datetime.now(TZ) - timedelta(minutes=5)).isoformat()})
    ctx = _ctx(db)
    query = SimpleNamespace(data="love:baris", answer=AsyncMock(), edit_message_reply_markup=AsyncMock())
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=99), message=None, callback_query=query)
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(upd, ctx)
    assert "kus" not in db.values


def test_stats():
    now = datetime(2026, 10, 20, 12, tzinfo=TZ)
    log = partner.log_kus(None, now - timedelta(days=30, minutes=10), now - timedelta(days=30))
    log = partner.log_kus(log, now - timedelta(hours=3), now - timedelta(hours=1))
    s = partner.stats(log, now)
    assert (s["total"], s["this_month"], s["longest"], s["last"], s["avg"]) == (2, 1, "2 saat", "2 saat", "1 saat 5 dakika")
    assert "Bu ay: 1 kez" in partner.stats_text(s)
    assert partner.stats_text(partner.stats([], now)).startswith("📊 Henüz")


async def test_partner_cannot_reach_owner_handlers():
    ctx = _ctx(KV())
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(_upd(99, "/notlar"), ctx)
    assert "Saha rehberi" in _sent(ctx.bot.send_message, 99)[-1].args[1]


async def test_old_kus_button_still_works():
    db = KV()
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(_upd(99, "😤 Küstüm"), _ctx(db))
    assert "kus" in db.values


async def test_help_button_sends_guide():
    ctx = _ctx(KV())
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(_upd(99, partner.YARDIM), ctx)
    reply = _sent(ctx.bot.send_message, 99)[-1]
    assert "Boykot başlasın" in reply.args[1] and "07:00" in reply.args[1] and "Moralim bozuk" in reply.args[1]
    assert reply.kwargs["reply_markup"].keyboard[2][0].text == partner.YARDIM


async def test_partner_reminder_goes_to_partner():
    ctx = _ctx(KV())
    await botmod.send_reminder(ctx.bot, ctx.bot_data, "Sınav", "partner")
    calls = [c.args for c in ctx.bot.send_message.await_args_list]
    assert calls[0] == (99, "⏰ Kayra hatırlatıyor: Sınav")
    assert calls[1][0] == 42


async def test_unreachable_partner_warns_owner():
    ctx = _ctx(KV())
    ctx.bot.send_message = AsyncMock(side_effect=[Exception("Forbidden"), None])
    assert await botmod.notify_partner(ctx.bot, ctx.bot_data, "x") is False
    assert "ulaşılamadı" in ctx.bot.send_message.await_args.args[1]


async def test_partner_send_log_records_success_and_failure(monkeypatch):
    db = KV()
    ctx = _ctx(db)
    brief = SimpleNamespace(weather=None, text="x", text_without_weather="x")

    async def fake_build(bot_data, p, today, evening=False):
        return brief, {"photo_card": False}

    monkeypatch.setattr(botmod, "build_partner_briefing", fake_build)
    monkeypatch.setattr(botmod, "send_gif", AsyncMock())
    monkeypatch.setattr(botmod, "deliver_briefing", AsyncMock())

    await botmod.send_partner_briefing(ctx, evening=True)
    assert db.values["partner_sends"][0]["ok"] is True
    assert db.values["partner_sends"][0]["kind"] == "aksam"

    monkeypatch.setattr(botmod, "deliver_briefing", AsyncMock(side_effect=Exception("boom")))
    await botmod.send_partner_briefing(ctx, evening=True)
    assert db.values["partner_sends"][0]["ok"] is False
    assert "boom" in db.values["partner_sends"][0]["error"]


async def test_partner_send_log_caps_entries(monkeypatch):
    db = KV()
    ctx = _ctx(db)
    for _ in range(botmod.PARTNER_SEND_LOG_MAX + 5):
        await botmod.log_partner_send(ctx.bot_data, "sabah", True)
    assert len(db.values["partner_sends"]) == botmod.PARTNER_SEND_LOG_MAX


def test_partner_briefing_inherits_owner_sections_with_own_news():
    owner = copy.deepcopy(botmod.settings.DEFAULTS)
    owner["sections"]["finance"] = False
    owner["sections"]["news"] = True
    owner["news_topics"] = ["teknoloji"]
    owner["news_count"] = 7

    merged = botmod.partner_briefing_settings(PARTNER, owner)

    assert merged["sections"] == owner["sections"]
    assert merged["sections"]["finance"] is False
    assert merged["news_topics"] == PARTNER["news_topics"]
    assert merged["news_count"] == botmod.PARTNER_NEWS_COUNT


def test_owner_rows_have_seviyorum():
    assert partner.SEVIYORUM in partner.owner_rows()[0]


async def test_partner_seviyorum_notifies_owner():
    ctx = _ctx(KV())
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(_upd(99, partner.SEVIYORUM), ctx)
    assert "seni seviyor" in _sent(ctx.bot.send_animation, 42)[-1].kwargs["caption"]
    assert _sent(ctx.bot.send_message, 99)[-1].args[1].startswith("❤️")


async def test_owner_seviyorum_sends_gif_to_partner():
    ctx = _ctx(KV())
    await botmod.owner_love_action(ctx, "seviyorum")
    gif = _sent(ctx.bot.send_animation, 99)[-1]
    assert "seni seviyor" in gif.kwargs["caption"]
    assert _sent(ctx.bot.send_message, 42)[-1].args[1] == "❤️ İlettim."


def _cd_db(exams):
    db = KV()
    db.exam_calendar_between = AsyncMock(return_value=exams)
    return db


async def test_countdown_lines_exams_holidays_and_weekend():
    exam = {"id": 1, "subject": "Matematik", "kind": "yazılı", "branch": "", "day": date(2026, 11, 25), "time": ""}
    lines = await botmod.countdown_lines({"db": _cd_db([exam])}, date(2026, 11, 22))
    joined = "\n".join(lines)
    assert "Matematik" in joined and "3 gün" in joined
    assert "1. dönem ara tatili" not in joined


async def test_countdown_lines_without_exams_says_none():
    lines = await botmod.countdown_lines({"db": _cd_db([])}, date(2026, 11, 22))
    assert "sınavın yok" in lines[0]


async def test_countdown_lines_holiday_ending():
    lines = await botmod.countdown_lines({"db": _cd_db([])}, date(2026, 11, 19))
    assert any("bitmesine 1 gün" in line for line in lines)


async def test_partner_briefing_includes_countdown_and_love(monkeypatch):
    captured = {}

    async def fake_build(today, src, settings, evening=False, from_hour=0, name="", top_lines=()):
        captured["top"] = list(top_lines)
        return SimpleNamespace(weather=None, text="x", text_without_weather="x")

    async def fake_love(bot_data, today):
        return ["💕 Özel gün"]

    monkeypatch.setattr(botmod.briefing, "build", fake_build)
    monkeypatch.setattr(botmod.briefing, "make_sources", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(botmod, "love_lines", fake_love)

    db = _cd_db([])
    bot_data = {"cfg": SimpleNamespace(tz=TZ), "db": db, "llm": None, "http": None}
    await botmod.build_partner_briefing(bot_data, PARTNER, date(2026, 11, 22))
    assert any("sınavın yok" in line for line in captured["top"])
    assert "💕 Özel gün" in captured["top"]

    await botmod.build_partner_briefing(bot_data, PARTNER, date(2026, 11, 22), evening=True)
    assert "💕 Özel gün" not in captured["top"]
    assert any("sınavın yok" in line for line in captured["top"])
