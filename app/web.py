import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web

from dataclasses import asdict

from app import bot, card, reminders, schedule, settings, weather
from app.status import STARTED_AT
from app.webauth import AuthError, verify_init_data

log = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"
DERSHANE_DAYS = ("cumartesi", "pazar")
TOMORROW_FROM_HOUR = 18
TG_APP = web.AppKey("tg", object)


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _json(data, status: int = 200) -> web.Response:
    body = json.dumps(data, ensure_ascii=False, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))
    return web.Response(text=body, status=status, content_type="application/json")


@web.middleware
async def errors(request: web.Request, handler):
    try:
        return await handler(request)
    except ApiError as e:
        return _json({"error": e.message}, e.status)
    except (settings.SettingsError, schedule.ScheduleError, reminders.ReminderError) as e:
        return _json({"error": str(e)}, 400)
    except web.HTTPException:
        raise
    except Exception:
        log.exception("Panel API hatası: %s %s", request.method, request.path)
        return _json({"error": "Sunucuda bir hata oldu"}, 500)


@web.middleware
async def auth(request: web.Request, handler):
    if request.path.startswith("/api/"):
        cfg = request.app[TG_APP].bot_data["cfg"]
        header = request.headers.get("Authorization", "")
        if not header.startswith("tma "):
            raise ApiError(401, "Panel yalnızca Telegram içinden açılabilir")
        try:
            user = verify_init_data(header[4:], cfg.telegram_token)
        except AuthError as e:
            raise ApiError(401, str(e)) from e
        if int(user["id"]) != cfg.owner_id:
            raise ApiError(403, "Bu panel sana ait değil")
    return await handler(request)


def _tg(request):
    return request.app[TG_APP]


def _data(request):
    return request.app[TG_APP].bot_data


async def _body(request):
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ApiError(400, "Geçersiz JSON") from e


def _int(request, name: str) -> int:
    try:
        return int(request.match_info[name])
    except ValueError as e:
        raise ApiError(404, "Bulunamadı") from e


async def health(request):
    return web.Response(text="ok")


async def index(request):
    return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


async def status(request):
    d = _data(request)
    jobs = _tg(request).job_queue.get_jobs_by_name("sabah-ozeti")
    pending = await d["db"].pending_reminders()
    errors_buf = d.get("errors")
    return _json({
        "started_at": STARTED_AT,
        "uptime_s": int((datetime.now(timezone.utc) - STARTED_AT).total_seconds()),
        "next_briefing": jobs[0].next_t if jobs and getattr(jobs[0], "next_t", None) else None,
        "errors": errors_buf.records() if errors_buf else [],
        "settings": await bot.load_settings(d),
        "reminder_count": len(pending),
    })


def _now(tz) -> datetime:
    return datetime.now(tz)


async def get_weather(request):
    d = _data(request)
    now = _now(d["cfg"].tz)
    is_tomorrow = now.hour >= TOMORROW_FROM_HOUR
    day = now.date() + timedelta(days=1) if is_tomorrow else now.date()
    w = await weather.fetch(d["cfg"].lat, d["cfg"].lon, d["cfg"].tz.key, d["http"], day)
    return _json({**asdict(w), "label": weather.CONDITION_TR.get(w.condition, ""), "day": day, "is_tomorrow": is_tomorrow})


async def get_settings(request):
    return _json(await bot.load_settings(_data(request)))


async def put_settings(request):
    d = _data(request)
    value = settings.validate(await _body(request))
    await d["db"].save_settings(value)
    bot.reschedule_briefing(_tg(request).job_queue, value["briefing_time"], d["cfg"].tz)
    return _json(value)


async def get_schedules(request):
    return _json(await _data(request)["db"].all_schedules())


def _schedule_key(request) -> tuple[str, str]:
    kind = request.match_info["kind"]
    day = request.match_info.get("day", "")
    if (kind, day) == ("okul", "") or (kind == "dershane" and day in DERSHANE_DAYS):
        return kind, day
    raise ApiError(404, "Böyle bir program yok")


async def put_schedule(request):
    kind, day = _schedule_key(request)
    body = await _body(request)
    data = schedule.validate_okul(body) if kind == "okul" else schedule.validate_dershane(body)
    await _data(request)["db"].save_schedule(kind, day, data)
    return _json(data)


async def delete_schedule(request):
    kind, day = _schedule_key(request)
    await _data(request)["db"].delete_schedule(kind, day)
    return _json({"ok": True})


async def get_notes(request):
    return _json(await _data(request)["db"].search_notes(request.query.get("q", "")))


async def delete_note(request):
    if not await _data(request)["db"].delete_note(_int(request, "id")):
        raise ApiError(404, "Not bulunamadı")
    return _json({"ok": True})


async def get_reminders(request):
    return _json(await _data(request)["db"].pending_reminders())


async def post_reminder(request):
    d = _data(request)
    text = str((await _body(request)).get("text", "")).strip()
    if not text:
        raise ApiError(400, "Hatırlatıcı metni boş")
    when, what = await reminders.parse(text, datetime.now(d["cfg"].tz), d["llm"])
    rid = await d["db"].add_reminder(what, when)
    bot.schedule_reminder(_tg(request).job_queue, rid, when, what)
    return _json({"id": rid, "text": what, "due_at": when})


async def delete_reminder(request):
    rid = _int(request, "id")
    for job in _tg(request).job_queue.get_jobs_by_name(f"rem-{rid}"):
        job.schedule_removal()
    if not await _data(request)["db"].delete_reminder(rid):
        raise ApiError(404, "Hatırlatıcı bulunamadı")
    return _json({"ok": True})


async def preview(request):
    d = _data(request)
    now = _now(d["cfg"].tz)
    s_now = await bot.load_settings(d)
    hour, minute = map(int, s_now["briefing_time"].split(":"))
    today = now.date() if (now.hour, now.minute) < (hour, minute) else now.date() + timedelta(days=1)
    result, s = await bot.build_briefing(d, today)
    image = None
    if s["photo_card"] and result.weather:
        try:
            image = base64.b64encode(card.render_card(result.weather.w, result.weather.hints, today)).decode()
        except Exception:
            log.exception("Önizleme kartı çizilemedi")
    text = result.text_without_weather if image else result.text
    caption = bot.photo_caption(result.weather) if image else None
    return _json({"text": text, "card": image, "caption": caption})


async def send_now(request):
    tg = _tg(request)
    await bot.send_briefing(SimpleNamespace(bot=tg.bot, bot_data=tg.bot_data))
    return _json({"ok": True})


def build_web_app(tg_app) -> web.Application:
    app = web.Application(middlewares=[errors, auth])
    app[TG_APP] = tg_app
    app.add_routes([
        web.get("/health", health),
        web.get("/", index),
        web.static("/static", STATIC),
        web.get("/api/status", status),
        web.get("/api/weather", get_weather),
        web.get("/api/settings", get_settings),
        web.put("/api/settings", put_settings),
        web.get("/api/schedules", get_schedules),
        web.put("/api/schedules/{kind}", put_schedule),
        web.put("/api/schedules/{kind}/{day}", put_schedule),
        web.delete("/api/schedules/{kind}", delete_schedule),
        web.delete("/api/schedules/{kind}/{day}", delete_schedule),
        web.get("/api/notes", get_notes),
        web.delete("/api/notes/{id}", delete_note),
        web.get("/api/reminders", get_reminders),
        web.post("/api/reminders", post_reminder),
        web.delete("/api/reminders/{id}", delete_reminder),
        web.get("/api/briefing/preview", preview),
        web.post("/api/briefing/send", send_now),
    ])
    return app


async def start_web(tg_app, port: int) -> web.AppRunner:
    runner = web.AppRunner(build_web_app(tg_app), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    return runner
