import base64
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web

from dataclasses import asdict

from datetime import date
from telegram.error import TelegramError

from app import bot, calendar_tr, card, daily_tasks, examcal, gifs, love, news, partner, reminders, schedule, school, settings, tasks, weather
from app.llm import LLMError
from app.status import STARTED_AT
from app.webauth import AuthError, verify_init_data

log = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"
DERSHANE_DAYS = ("cumartesi", "pazar")
TOMORROW_FROM_HOUR = 18
EXAM_WINDOW_DAYS = 120
TG_APP = web.AppKey("tg", object)
PARTNER_PATHS = {
    "/api/me", "/api/partner/self", "/api/love/state", "/api/love/action",
    "/api/love/nickname", "/api/love/undo", "/api/love/templates", "/api/daily-tasks",
}
PARTNER_ACTIONS = {"kus": partner.KUS, "baris": partner.BARIS, "ozledim": partner.OZLEDIM, "seviyorum": partner.SEVIYORUM, "moral": partner.MORAL}
OWNER_ACTIONS = {"kus", "baris", "gonul", "ozledim", "seviyorum", "moral"}


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
    except LLMError:
        log.exception("Panel isteğinde LLM hatası: %s %s", request.method, request.path)
        return _json({"error": "Yapay zekâya şu an ulaşamıyorum, birazdan tekrar dener misin?"}, 503)
    except school.NotThis:
        return _json({"error": "Bunu anlayamadım, örneğe benzer şekilde yazar mısın?"}, 400)
    except tasks.NotATask:
        return _json({"error": "Bunu ödev ya da sınav olarak anlayamadım, tarihiyle yazar mısın?"}, 400)
    except (settings.SettingsError, schedule.ScheduleError, reminders.ReminderError, tasks.TaskError, examcal.ExamCalError,
            school.SchoolError) as e:
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
        p = request.app[TG_APP].bot_data.get("partner")
        if int(user["id"]) == cfg.owner_id:
            request["role"] = "owner"
        elif p and int(user["id"]) == p["id"]:
            if request.path not in PARTNER_PATHS:
                raise ApiError(403, "Bu bölüm sana kapalı")
            request["role"] = "partner"
        else:
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
        "partner_sends": await d["db"].get_kv("partner_sends") or [],
        "settings": await bot.load_settings(d),
        "reminder_count": len(pending),
    })


def _now(tz) -> datetime:
    return datetime.now(tz)


async def _next_day(d):
    s = await bot.load_settings(d)
    return bot.next_briefing_day(_now(d["cfg"].tz), s["briefing_time"])


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
    bot.reschedule_evening(_tg(request).job_queue, value, d["cfg"].tz)
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


async def get_tasks(request):
    d = _data(request)
    today = _now(d["cfg"].tz).date()
    items = await d["db"].list_tasks(include_done=request.query.get("all") == "1")
    return _json([{**t, "label": tasks.relative(t["due"], today)} for t in items])


async def post_task(request):
    d = _data(request)
    text = str((await _body(request)).get("text", "")).strip()
    if not text:
        raise ApiError(400, "Ödev ya da sınav metni boş")
    kind, title, due = await tasks.parse(text, _now(d["cfg"].tz).date(), d["llm"])
    tid = await d["db"].add_task(kind, title, due)
    return _json({"id": tid, "kind": kind, "title": title, "due": due, "done": False})


async def patch_task(request):
    done = (await _body(request)).get("done")
    if not isinstance(done, bool):
        raise ApiError(400, "done true ya da false olmalı")
    if not await _data(request)["db"].set_task_done(_int(request, "id"), done):
        raise ApiError(404, "Ödev ya da sınav bulunamadı")
    return _json({"ok": True})


async def delete_task(request):
    if not await _data(request)["db"].delete_task(_int(request, "id")):
        raise ApiError(404, "Ödev ya da sınav bulunamadı")
    return _json({"ok": True})


async def get_exam_calendar(request):
    d = _data(request)
    today = _now(d["cfg"].tz).date()
    items = await d["db"].exam_calendar_between(today, today + timedelta(days=EXAM_WINDOW_DAYS))
    return _json([{**e, "label": examcal.relative(e["day"], today)} for e in items])


async def post_exam_calendar(request):
    d = _data(request)
    today = _now(d["cfg"].tz).date()
    try:
        exam = await examcal.parse_text(await _text_body(request), today, d["llm"])
    except examcal.NotAnExam as e:
        raise ApiError(400, "Bunu sınav olarak anlayamadım, tarihiyle yazar mısın?") from e
    eid = await d["db"].add_exam_entry(exam["subject"], exam["day"], exam["at_time"], exam["kind"], exam["branch"])
    return _json({**exam, "id": eid, "label": examcal.relative(exam["day"], today)})


async def get_school(request):
    d = _data(request)
    db = d["db"]
    s = await bot.load_settings(d)
    today = _now(d["cfg"].tz).date()
    yks = date.fromisoformat(s["yks_date"])
    subjects, overall = school.averages(await db.list_grades(), school.subject_hours(await db.get_schedule("okul", "")))
    rows = school.school_year_rows(await db.list_absences(), today)
    exams = await db.list_exams()
    return _json({
        "yks": {"date": yks, "estimated": s["yks_estimated"], "days_left": (yks - today).days},
        "holiday": calendar_tr.holiday_on(today),
        "calendar": [{"start": a, "end": b, "name": n, "days": (a - today).days} for a, b, n in calendar_tr.EVENTS if b >= today],
        "grades": {"subjects": subjects, "overall": overall},
        "absences": {"rows": rows, "totals": school.absence_totals(rows),
                     "limits": {"unexcused": school.UNEXCUSED_LIMIT, "total": school.TOTAL_LIMIT}},
        "exams": exams,
        "summaries": {k: school.exam_summary(exams, k, s.get(f"target_{k.lower()}")) for k in ("TYT", "AYT")},
        "targets": {"TYT": s.get("target_tyt"), "AYT": s.get("target_ayt")},
        "exam_calendar": [
            {**e, "label": examcal.relative(e["day"], today)}
            for e in await db.exam_calendar_between(today, today + timedelta(days=EXAM_WINDOW_DAYS))
        ],
    })


async def _text_body(request) -> str:
    text = str((await _body(request)).get("text", "")).strip()
    if not text:
        raise ApiError(400, "Metin boş")
    return text


async def post_grade(request):
    d = _data(request)
    subject, label, score = await school.parse_grade(await _text_body(request), d["llm"])
    gid = await d["db"].add_grade(subject, label, score)
    return _json({"id": gid, "subject": subject, "label": label, "score": score})


async def post_exam(request):
    d = _data(request)
    kind, total, details = await school.parse_exam(await _text_body(request), d["llm"])
    taken = _now(d["cfg"].tz).date()
    eid = await d["db"].add_exam(kind, total, details, taken)
    return _json({"id": eid, "kind": kind, "total": total, "details": details, "taken": taken})


async def post_absence(request):
    d = _data(request)
    body = await _body(request)
    day, excused, half = school.parse_absence_result(
        {"day": body.get("day") or "x", "excused": body.get("excused") is True, "half": body.get("half") is True},
        _now(d["cfg"].tz).date(),
    )
    aid = await d["db"].add_absence(day, excused, half)
    return _json({"id": aid, "day": day, "excused": excused, "half": half})


def _deleter(method: str, label: str):
    async def handler(request):
        if not await getattr(_data(request)["db"], method)(_int(request, "id")):
            raise ApiError(404, f"{label} bulunamadı")
        return _json({"ok": True})
    return handler


async def preview(request):
    d = _data(request)
    today = await _next_day(d)
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
    context = SimpleNamespace(bot=tg.bot, bot_data=tg.bot_data)
    today = await _next_day(tg.bot_data)
    await bot.send_briefing(context, today)
    if tg.bot_data.get("partner"):
        await bot.send_partner_briefing(context, today)
    return _json({"ok": True})


def _partner_or_404(d) -> dict:
    p = d.get("partner")
    if not p:
        raise ApiError(404, "Henüz sevgilin eklenmedi")
    return p


async def me(request):
    d = _data(request)
    p = d.get("partner")
    name = p["name"] if request["role"] == "partner" else "Kayra"
    result = {"role": request["role"], "name": name, "topics": news.CATALOG}
    if request["role"] == "partner":
        owner_settings = await bot.load_settings(d)
        result["briefing"] = {
            "sections": owner_settings["sections"],
            "photo_card": owner_settings["photo_card"],
            "news_count": bot.PARTNER_NEWS_COUNT,
            "evening_time": partner.EVENING_TIME,
        }
    return _json(result)


async def get_partner_self(request):
    p = _partner_or_404(_data(request))
    return _json({k: p[k] for k in partner.SELF_KEYS})


async def put_partner_self(request):
    d = _data(request)
    p = _partner_or_404(d)
    value = {**p, **partner.validate_self(await _body(request))}
    await bot.save_partner(d, _tg(request).job_queue, value)
    return _json({k: value[k] for k in partner.SELF_KEYS})


async def get_partner(request):
    d = _data(request)
    db = d["db"]
    kus, days, now = await db.get_kv("kus"), await db.list_special_days(), _now(d["cfg"].tz)
    return _json({
        "partner": d.get("partner"),
        "kus": kus,
        "kus_for": partner.duration(datetime.fromisoformat(kus["since"]), now) if kus else None,
        "notes": await db.pending_love_notes(),
        "days": days,
        "lines": love.lines(days, now.date()),
        "stats": partner.stats(await db.get_kv("kus_log"), now),
    })


async def put_partner(request):
    d = _data(request)
    p = _partner_or_404(d)
    value = {**p, **partner.validate_owner(await _body(request))}
    await bot.save_partner(d, _tg(request).job_queue, value)
    return _json(value)


async def delete_partner(request):
    await bot.remove_partner(_data(request), _tg(request).job_queue)
    return _json({"ok": True})


async def post_invite(request):
    d = _data(request)
    invite = partner.new_invite(_now(d["cfg"].tz))
    await d["db"].set_kv("invite", invite)
    return _json({"link": f"https://t.me/{_tg(request).bot.username}?start={invite['code']}", "expires": invite["expires"]})


async def _love_state(d, role: str) -> dict:
    kus = await d["db"].get_kv("kus")
    since = partner.duration(datetime.fromisoformat(kus["since"]), _now(d["cfg"].tz)) if kus else None
    p = d.get("partner") or {}
    fallback = p.get("name", "Sevgilin") if role == "owner" else "Kayra"
    nicknames = await d["db"].get_kv("love_nicknames") or {}
    forms = partner.nickname_forms(nicknames.get(role, ""), fallback)
    undo = (await d["db"].get_kv("love_undo") or {}).get(role)
    can_undo = False
    if undo and undo.get("chat_id") == (p.get("id") if role == "owner" else d["cfg"].owner_id):
        sent_at = datetime.fromisoformat(undo["sent_at"])
        age = _now(d["cfg"].tz) - sent_at
        can_undo = timedelta(0) <= age < timedelta(hours=48)
    return {
        "kus": bool(kus),
        "kus_for": since,
        "recipient_address": forms["address"],
        "can_undo": can_undo,
    }


async def get_love_state(request):
    d = _data(request)
    _partner_or_404(d)
    return _json(await _love_state(d, request["role"]))


async def love_nickname(request):
    d = _data(request)
    _partner_or_404(d)
    key = request["role"]
    nicknames = await d["db"].get_kv("love_nicknames") or {}
    if request.method == "PUT":
        nickname = partner.validate_nickname(await _body(request))
        nicknames[key] = nickname
        await d["db"].set_kv("love_nicknames", nicknames)
    return _json({"nickname": nicknames.get(key, "")})


async def undo_love_action(request):
    d = _data(request)
    p = _partner_or_404(d)
    role = request["role"]
    actions = await d["db"].get_kv("love_undo") or {}
    action = actions.get(role)
    target_id = p["id"] if role == "owner" else d["cfg"].owner_id
    if not action or action.get("chat_id") != target_id:
        raise ApiError(409, "Geri alınabilecek bir mesaj yok")
    sent_at = datetime.fromisoformat(action["sent_at"])
    age = _now(d["cfg"].tz) - sent_at
    if age < timedelta(0) or age >= timedelta(hours=48):
        raise ApiError(409, "Mesajı geri alma süresi dolmuş")
    try:
        await _tg(request).bot.delete_message(target_id, action["message_id"])
    except TelegramError as e:
        log.warning("Karşı taraftaki mesaj silinemedi (%s): %r", role, e)
        raise ApiError(409, "Mesaj karşı tarafın sohbetinden silinemedi") from e
    actions.pop(role, None)
    await d["db"].set_kv("love_undo", actions)
    return _json(await _love_state(d, role))


async def love_templates(request):
    d = _data(request)
    _partner_or_404(d)
    if request["role"] == "partner":
        kinds = ("kus", "baris", "ozledim", "seviyorum", "moral")
        key = "partner_love_templates"
        labels = {"kus": "Boykot başlasın", "baris": "Barıştık", "ozledim": "Özledim", "seviyorum": "Seni seviyorum", "moral": "Moralim bozuk"}
    else:
        kinds = ("kus", "baris", "gonul", "ozledim", "seviyorum", "moral")
        key = "owner_love_templates"
        labels = {"kus": "Boykot başlat", "baris": "Barıştık", "gonul": "Gönlünü al", "ozledim": "Özledim", "seviyorum": "Seni seviyorum", "moral": "Moral ver"}
    stored = await d["db"].get_kv(key) or {}
    nicknames = await d["db"].get_kv("love_nicknames") or {}
    recipient_name = "Kayra" if request["role"] == "partner" else d["partner"]["name"]
    sender_name = d["partner"]["name"] if request["role"] == "partner" else "Kayra"
    names = partner.nickname_forms(nicknames.get(request["role"], ""), recipient_name, sender_name)
    gif_kinds = {
        "kus": "boykot",
        "baris": "baris",
        "gonul": "gonlunu_al",
        "ozledim": "ozledim",
        "seviyorum": "seviyorum",
        "moral": "moral",
    }
    if request.method == "PUT":
        body = await _body(request)
        result = {}
        for kind in kinds:
            item = body.get(kind)
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()[:500]
            gif_id = str(item.get("gif", "")).strip()
            gif_kind = gif_kinds[kind]
            if gif_id and not gif_id.lower().startswith(("http://", "https://")) and gif_id not in gifs.PACKS[gif_kind]:
                # Allow Giphy media IDs as well as direct URLs.
                if not re.fullmatch(r"[A-Za-z0-9_-]{8,40}", gif_id):
                    raise ApiError(400, "Geçersiz GIF")
            result[kind] = {"text": text, "gif": gif_id}
        await d["db"].set_kv(key, result)
        stored = result
    actions = []
    for kind in kinds:
        gif_kind = gif_kinds[kind]
        gif_options = [{"id": gif_id, "url": gifs.GIPHY.format(gif_id)} for gif_id in gifs.PACKS[gif_kind]]
        actions.append({
            "key": kind,
            "label": labels[kind],
            "gifs": gif_options,
            "preview_text": bot.default_love_caption(request["role"], kind, names["reference"]),
        })
    return _json({"templates": stored, "actions": actions})


async def daily_tasks_handler(request):
    d = _data(request)
    p = _partner_or_404(d)
    db = d["db"]
    now = _now(d["cfg"].tz)
    today = now.date()
    role = request["role"]
    owner_name = "Kayra"
    partner_name = p["name"]
    if now.hour < daily_tasks.START_HOUR:
        if request.method != "GET":
            raise ApiError(409, "Görevler 07:00'de başlayacak")
        return _json({"today": today.isoformat(), "available": False, "task": None, "window": "07:00–23:00"})

    state = await db.get_kv("daily_tasks") or {}
    if now.hour < daily_tasks.END_HOUR:
        state = await daily_tasks.assign_day(db, d.get("llm"), today, owner_name, partner_name)
    elif today.isoformat() in state.get("days", {}):
        context = SimpleNamespace(bot=_tg(request).bot, bot_data=d)
        await bot.end_daily_tasks(context)
        state = await db.get_kv("daily_tasks") or {}
    else:
        if request.method != "GET":
            raise ApiError(409, "Bugünkü görev süresi sona erdi")
        return _json({"today": today.isoformat(), "available": False, "task": None, "window": "07:00–23:00"})
    day = state["days"][today.isoformat()]

    if request.method == "GET":
        own = {**day[role], "progress_percent": daily_tasks.progress_percent(day[role])}
        result = {
            "today": today.isoformat(),
            "available": now.hour < daily_tasks.END_HOUR,
            "task": own,
            "window": "07:00–23:00",
        }
        counter_role = "partner" if role == "owner" else "owner"
        counter_task = day[counter_role]
        counter = {
            "name": partner_name if counter_role == "partner" else owner_name,
            "status": counter_task["status"],
            "penalty": counter_task.get("penalty"),
            "penalty_options": counter_task.get("penalty_options"),
            "progress_percent": daily_tasks.progress_percent(counter_task),
        }
        if counter_task.get("verification_steps"):
            counter.update({
                "text": counter_task["text"],
                "verification_steps": counter_task["verification_steps"],
                "verified_steps": counter_task.get("verified_steps", []),
            })
        result[counter_role] = counter
        return _json(result)

    body = await _body(request)
    action = str(body.get("action", ""))
    if action not in ("complete", "fail", "verify", "penalty"):
        raise ApiError(400, "Geçersiz görev işlemi")
    own = day[role]
    if now.hour >= daily_tasks.END_HOUR and action != "penalty":
        raise ApiError(409, "Görev süresi 23:00'te sona erdi")
    if action in ("complete", "fail") and own.get("verification_steps"):
        raise ApiError(400, "Bu görev için ilerlemeyi karşı taraf doğruluyor")
    if action == "complete":
        own["status"] = "completed"
        own["outcome"] = "Tamamlandı"
    elif action == "fail":
        own["status"] = "failed"
        own["outcome"] = "Yapamadı"
        own["penalty_options"] = daily_tasks.select_penalties(today, role)
        counter_role = "partner" if role == "owner" else "owner"
        await _tg(request).bot.send_message(
            p["id"] if counter_role == "partner" else d["cfg"].owner_id,
            f"Görevini yapamadı: {own['text']}\n"
            f"Ceza seçeneklerinden birini Görevler sekmesinden seçebilirsin.",
        )
    elif action == "verify":
        target_role = str(body.get("target", ""))
        if target_role not in ("owner", "partner") or target_role == role:
            raise ApiError(400, "Yalnız karşı tarafın doğrulanabilir görevini güncelleyebilirsin")
        target = day[target_role]
        verification_steps = target.get("verification_steps")
        completed_steps = body.get("completed_steps")
        if not verification_steps or target["status"] not in ("pending", "completed"):
            raise ApiError(400, "Bu görev için ilerleme doğrulaması kullanılamıyor")
        if not isinstance(completed_steps, list) or any(
            type(index) is not int or not 0 <= index < len(verification_steps)
            for index in completed_steps
        ):
            raise ApiError(400, "Geçersiz görev adımı")
        completed_steps = sorted(set(completed_steps))
        target["verified_steps"] = completed_steps
        percent = daily_tasks.progress_percent(target)
        if percent == 100:
            target["status"] = "completed"
            target["outcome"] = "Karşı taraf tamamlandığını doğruladı"
        else:
            target["status"] = "pending"
            target["outcome"] = None
        await db.set_kv("daily_tasks", state)
        target_id = d["cfg"].owner_id if target_role == "owner" else p["id"]
        try:
            await _tg(request).bot.send_message(
                target_id,
                f"Karşı taraf günlük görevindeki ilerlemeyi güncelledi: "
                f"%{percent} ({len(completed_steps)}/{len(verification_steps)} madde).",
            )
        except TelegramError:
            log.exception("Günlük görev ilerleme bildirimi gönderilemedi (%s)", target_role)
        return _json({"today": today.isoformat(), "task": own})
    else:
        target_role = str(body.get("target", ""))
        index = body.get("index")
        if target_role not in ("owner", "partner") or target_role == role:
            raise ApiError(400, "Ceza yalnız karşı tarafa verilebilir")
        target = day[target_role]
        if target["status"] != "failed":
            raise ApiError(400, "Bu görev için ceza beklenmiyor")
        options = target.get("penalty_options") or daily_tasks.PENALTIES
        if not isinstance(index, int) or not 0 <= index < len(options):
            raise ApiError(400, "Geçersiz ceza seçimi")
        target["penalty"] = options[index]
        target["status"] = "penalty"
        target_id = d["cfg"].owner_id if target_role == "owner" else p["id"]
        await _tg(request).bot.send_message(
            target_id,
            f"Karşı taraf cezanı seçti. Cezan bu: {target['penalty']}",
        )
    await db.set_kv("daily_tasks", state)
    own = day[role]
    return _json({"today": today.isoformat(), "task": own})


async def post_love_action(request):
    tg, d = _tg(request), _data(request)
    _partner_or_404(d)
    action = str((await _body(request)).get("action", ""))
    ctx = SimpleNamespace(bot=tg.bot, bot_data=tg.bot_data, job_queue=tg.job_queue)
    if request["role"] == "partner" and action in PARTNER_ACTIONS:
        await bot.partner_action(ctx, d, PARTNER_ACTIONS[action])
    elif request["role"] == "owner" and action in OWNER_ACTIONS:
        await bot.owner_love_action(ctx, action)
    else:
        raise ApiError(400, "Bilinmeyen işlem")
    return _json(await _love_state(d, request["role"]))


async def post_love_note(request):
    text = love.validate_note(await _body(request))
    nid = await _data(request)["db"].add_love_note(text)
    return _json({"id": nid, "text": text})


async def post_special_day(request):
    row = love.validate_day(await _body(request))
    did = await _data(request)["db"].add_special_day(row["name"], row["day"], row["yearly"], row["counter"])
    return _json({"id": did, **row})


async def _no_cache_static(request, response):
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"


def build_web_app(tg_app) -> web.Application:
    app = web.Application(middlewares=[errors, auth])
    app.on_response_prepare.append(_no_cache_static)
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
        web.get("/api/tasks", get_tasks),
        web.post("/api/tasks", post_task),
        web.patch("/api/tasks/{id}", patch_task),
        web.delete("/api/tasks/{id}", delete_task),
        web.get("/api/exam-calendar", get_exam_calendar),
        web.post("/api/exam-calendar", post_exam_calendar),
        web.delete("/api/exam-calendar/{id}", _deleter("delete_exam_entry", "Sınav")),
        web.get("/api/school", get_school),
        web.post("/api/grades", post_grade),
        web.delete("/api/grades/{id}", _deleter("delete_grade", "Not")),
        web.post("/api/exams", post_exam),
        web.delete("/api/exams/{id}", _deleter("delete_exam", "Deneme")),
        web.post("/api/absences", post_absence),
        web.delete("/api/absences/{id}", _deleter("delete_absence", "Devamsızlık")),
        web.get("/api/briefing/preview", preview),
        web.post("/api/briefing/send", send_now),
        web.get("/api/me", me),
        web.get("/api/partner/self", get_partner_self),
        web.put("/api/partner/self", put_partner_self),
        web.get("/api/partner", get_partner),
        web.put("/api/partner", put_partner),
        web.delete("/api/partner", delete_partner),
        web.post("/api/partner/invite", post_invite),
        web.get("/api/love/state", get_love_state),
        web.post("/api/love/action", post_love_action),
        web.get("/api/love/nickname", love_nickname),
        web.put("/api/love/nickname", love_nickname),
        web.post("/api/love/undo", undo_love_action),
        web.get("/api/love/templates", love_templates),
        web.put("/api/love/templates", love_templates),
        web.get("/api/daily-tasks", daily_tasks_handler),
        web.post("/api/daily-tasks", daily_tasks_handler),
        web.post("/api/love-notes", post_love_note),
        web.delete("/api/love-notes/{id}", _deleter("delete_love_note", "Not")),
        web.post("/api/special-days", post_special_day),
        web.delete("/api/special-days/{id}", _deleter("delete_special_day", "Özel gün")),
    ])
    return app


async def start_web(tg_app, port: int) -> web.AppRunner:
    runner = web.AppRunner(build_web_app(tg_app), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    return runner
