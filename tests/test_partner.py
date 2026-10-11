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
        bot=SimpleNamespace(send_message=AsyncMock(), username="SahaBot", set_my_commands=AsyncMock()),
        job_queue=jq,
    )


def _upd(user_id, text):
    msg = SimpleNamespace(text=text, reply_text=AsyncMock())
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id, first_name="İlayda"), message=msg, callback_query=None)


async def test_kus_and_baris_flow():
    db = KV()
    ctx = _ctx(db)
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(_upd(99, partner.KUS), ctx)
    assert "kus" in db.values
    assert "küstü" in ctx.bot.send_message.await_args.args[1]
    assert ctx.job_queue.run_repeating.call_args.kwargs["name"] == "kus-hatirlat"

    db.values["kus"] = {"since": (datetime.now(TZ) - timedelta(minutes=30)).isoformat()}
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(_upd(99, partner.BARIS), ctx)
    assert "kus" not in db.values
    assert "barıştınız" in ctx.bot.send_message.await_args.args[1]


async def test_ozledim_notifies_owner():
    ctx = _ctx(KV())
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(_upd(99, partner.OZLEDIM), ctx)
    assert ctx.bot.send_message.await_args.args == (42, "🥺 İlayda seni özledi!")


async def test_partner_cannot_reach_owner_handlers():
    ctx = _ctx(KV())
    upd = _upd(99, "/notlar")
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(upd, ctx)
    assert "Ben Saha" in upd.message.reply_text.await_args.args[0]


async def test_claim_invite():
    inv = partner.new_invite(datetime.now(TZ))
    db = KV(invite=inv)
    ctx = _ctx(db, p=None)
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(_upd(99, f"/start {inv['code']}"), ctx)
    assert db.values["partner"]["id"] == 99 and "invite" not in db.values
    assert ctx.bot_data["partner"]["name"] == "İlayda"
    assert "katıldı" in ctx.bot.send_message.await_args.args[1]


async def test_wrong_invite_is_silent():
    db = KV(invite=partner.new_invite(datetime.now(TZ)))
    ctx = _ctx(db, p=None)
    upd = _upd(99, "/start yanlis")
    with pytest.raises(ApplicationHandlerStop):
        await botmod.gate(upd, ctx)
    assert "partner" not in db.values
    upd.message.reply_text.assert_not_awaited()


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
