import logging
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update, WebAppInfo
from telegram.ext import (
    Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler,
    TypeHandler, filters,
)

from telegram.error import Conflict, NetworkError, TimedOut

from app import briefing, calendar_tr, card, chat, intents, reminders, schedule, school, settings, tasks, weather
from app.llm import LLMError
from app.textutil import split_message

log = logging.getLogger(__name__)

LLM_DOWN = "⚠️ Yapay zekâya şu an ulaşamıyorum, birazdan tekrar dener misin?"

HELP = (
    "Merhaba Kayra, ben Saha! Yapabileceklerim:\n"
    "📷 Fotoğraf at → ders programı, ders notu ya da soru çözümü\n"
    "📊 \"fizik 1. yazılı 85\" → not, \"tyt deneme 78 net\" → deneme, \"bugün okula gitmedim\" → devamsızlık\n"
    "🎤 Bunların hepsini sesli mesajla da söyleyebilirsin\n"
    "🎤 Sesli mesaj at → nota çeviririm\n"
    "⏰ \"yarın 15'te faturayı hatırlat\" yaz → hatırlatırım\n"
    "💬 Başka bir şey yaz → notlarına ve programına bakarak cevaplarım\n\n"
    "/panel ayarlar ve program paneli\n"
    "/ozet sabah özetini şimdi gönder\n"
    "/program kayıtlı programlar\n"
    "/notlar son notlar\n"
    "/hatirlat <metin>\n"
    "📌 \"fizik ödevi cuma teslim\" yaz → ödev/sınav olarak kaydederim\n"
    "/odevler ödev ve sınavlar, /bitti <id> tamamlandı\n"
    "/hatirlaticilar bekleyen hatırlatıcılar\n"
    "/sil <id> hatırlatıcıyı sil"
)
PHOTO_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("📚 Ders programı", callback_data="pick:program")],
    [InlineKeyboardButton("📝 Ders notu", callback_data="pick:note")],
    [InlineKeyboardButton("❓ Soru çöz", callback_data="pick:solve")],
])
NOTE_PROMPT = (
    "Bu bir ders notu ya da tahta fotoğrafı. İçindeki yazıyı düzgün Türkçe metin olarak aynen yaz; "
    "formülleri düz metinle göster, okunmayan yerlere [?] koy. Sadece metni yaz."
)
SOLVE_OCR_PROMPT = "Bu bir sınav sorusu fotoğrafı. Soruyu ve varsa şıkları eksiksiz metin olarak aynen yaz. Sadece soruyu yaz, çözme."
SOLVE_SYSTEM = (
    "Sen bir YKS (TYT/AYT) öğretmenisin. Soruyu Türkçe, adım adım ve kısa çöz. "
    "Gereksiz uzatma; her adımda ne yaptığını bir cümleyle söyle. En sonda ayrı satırda 'Cevap: X' yaz."
)
KIND_BUTTONS = InlineKeyboardMarkup([
    [InlineKeyboardButton("🏫 Okul (hafta içi)", callback_data="kind:okul:")],
    [InlineKeyboardButton("📘 Dershane Cumartesi", callback_data="kind:dershane:cumartesi")],
    [InlineKeyboardButton("📘 Dershane Pazar", callback_data="kind:dershane:pazar")],
])
CONFIRM_BUTTONS = InlineKeyboardMarkup([[
    InlineKeyboardButton("✅ Kaydet", callback_data="save"),
    InlineKeyboardButton("🔁 Tekrar oku", callback_data="retry"),
]])
MAX_PENDING_PHOTOS = 10
KEEP_ALIVE_SECONDS = 600
MERGE_BUTTONS = InlineKeyboardMarkup([
    [InlineKeyboardButton("➕ Mevcut programa ekle", callback_data="merge")],
    [InlineKeyboardButton("♻️ Eskisinin yerine koy", callback_data="save")],
    [InlineKeyboardButton("🔁 Tekrar oku", callback_data="retry")],
])


def _deps(context):
    return context.bot_data


def _now(context) -> datetime:
    return datetime.now(_deps(context)["cfg"].tz)


async def send_text(bot, chat_id: int, text: str) -> None:
    for part in split_message(text):
        await bot.send_message(chat_id, part)


async def gate(update, context) -> None:
    user = update.effective_user
    if user is None or user.id != context.bot_data["cfg"].owner_id:
        raise ApplicationHandlerStop


COMMANDS = [
    BotCommand("panel", "Paneli aç"),
    BotCommand("ozet", "Sabah özetini şimdi gönder"),
    BotCommand("program", "Kayıtlı ders programları"),
    BotCommand("notlar", "Son notlar"),
    BotCommand("hatirlaticilar", "Bekleyen hatırlatıcılar"),
    BotCommand("odevler", "Ödev ve sınavlar"),
    BotCommand("yks", "YKS geri sayım ve deneme netleri"),
    BotCommand("ortalama", "Ders notları ve ortalama"),
    BotCommand("devamsizlik", "Devamsızlık durumu"),
]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP)


async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = _deps(context)["cfg"].public_url
    if not url:
        await update.message.reply_text("Panel adresi ayarlı değil (PUBLIC_URL). Render'da otomatik gelir.")
        return
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("Paneli aç", web_app=WebAppInfo(url=f"{url}/"))]])
    await update.message.reply_text("Saha paneli 👇", reply_markup=markup)


async def setup_menu(app: Application) -> None:
    cfg = app.bot_data["cfg"]
    await app.bot.set_my_commands(COMMANDS)
    if cfg.public_url:
        await app.bot.set_chat_menu_button(
            chat_id=cfg.owner_id, menu_button=MenuButtonWebApp(text="Panel", web_app=WebAppInfo(url=f"{cfg.public_url}/"))
        )


async def load_settings(bot_data) -> dict:
    return settings.merge(await bot_data["db"].get_settings(), bot_data["cfg"].briefing_time.strftime("%H:%M"))


def reschedule_briefing(job_queue, time_str: str, tz: ZoneInfo) -> None:
    for job in job_queue.get_jobs_by_name("sabah-ozeti"):
        job.schedule_removal()
    hour, minute = map(int, time_str.split(":"))
    job_queue.run_daily(send_briefing, time=time(hour, minute, tzinfo=tz), name="sabah-ozeti", data=time_str)


def reschedule_evening(job_queue, s: dict, tz: ZoneInfo) -> None:
    for job in job_queue.get_jobs_by_name("aksam-ozeti"):
        job.schedule_removal()
    if s["evening_enabled"]:
        hour, minute = map(int, s["evening_time"].split(":"))
        job_queue.run_daily(send_evening, time=time(hour, minute, tzinfo=tz), name="aksam-ozeti", data=s["evening_time"])


async def send_evening(context) -> None:
    await send_briefing(context, _now(context).date() + timedelta(days=1), evening=True)


async def build_briefing(bot_data, today, evening: bool = False) -> tuple[briefing.Briefing, dict]:
    s = await load_settings(bot_data)
    now = datetime.now(bot_data["cfg"].tz)
    ref_day = now.date()
    from_hour = now.hour if today == ref_day else 0
    src = briefing.make_sources(bot_data["cfg"], bot_data["db"], bot_data["llm"], bot_data["http"], today, s, ref_day)
    return await briefing.build(today, src, s, evening=evening, from_hour=from_hour), s


def photo_caption(info: briefing.WeatherInfo) -> str:
    return f"🌤 Buca — {weather.summary(info.w)}\n👕 {info.advice}"[:1024]


def next_briefing_day(now: datetime, briefing_time: str) -> date:
    hour, minute = map(int, briefing_time.split(":"))
    return now.date() if (now.hour, now.minute) < (hour, minute) else now.date() + timedelta(days=1)


async def send_briefing(context: ContextTypes.DEFAULT_TYPE, day: date | None = None, evening: bool = False) -> None:
    d = _deps(context)
    owner = d["cfg"].owner_id
    today = day or _now(context).date()
    result, s = await build_briefing(d, today, evening=evening)
    if s["photo_card"] and result.weather:
        try:
            png = card.render_card(result.weather.w, result.weather.hints, today)
            await context.bot.send_photo(owner, png, caption=photo_caption(result.weather))
        except TimedOut:
            log.warning("Hava kartı zaman aşımına uğradı, büyük ihtimalle ulaştı; hava tekrar gönderilmiyor")
        except Exception:
            log.exception("Hava kartı gönderilemedi, metne dönülüyor")
            await send_text(context.bot, owner, result.text)
            return
        await send_text(context.bot, owner, result.text_without_weather)
        return
    await send_text(context.bot, owner, result.text)


async def keep_alive(context) -> None:
    d = _deps(context)
    try:
        await d["http"].get(f"{d['cfg'].public_url}/health", timeout=15)
    except Exception as e:
        log.warning("Uyanık tutma isteği başarısız: %r", e)


def schedule_keep_alive(job_queue, public_url: str | None) -> None:
    if public_url:
        job_queue.run_repeating(keep_alive, interval=KEEP_ALIVE_SECONDS, first=60, name="uyanik-tut")


def is_reminder_request(text: str) -> bool:
    normalized = text.replace("İ", "i").replace("I", "ı").lower().strip()
    return "hatırlat" in normalized and not normalized.endswith("?")


async def ozet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    s = await load_settings(_deps(context))
    await send_briefing(context, next_briefing_day(_now(context), s["briefing_time"]))


async def program(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = schedule.format_all(await _deps(context)["db"].all_schedules())
    await send_text(context.bot, update.effective_chat.id, text)


async def notlar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = _deps(context)
    notes = await d["db"].recent_notes(10)
    if not notes:
        await update.message.reply_text("Henüz not yok.")
        return
    lines = [f"[{n['created_at'].astimezone(d['cfg'].tz):%d.%m %H:%M}] {n['text']}" for n in notes]
    await send_text(context.bot, update.effective_chat.id, "\n".join(lines))


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    file = await update.message.photo[-1].get_file()
    data = bytes(await file.download_as_bytearray())
    sent = await update.message.reply_text("Bu fotoğraf ne?", reply_markup=PHOTO_MENU)
    pending = context.user_data.setdefault("pending", {})
    pending[sent.message_id] = {"photo": data}
    while len(pending) > MAX_PENDING_PHOTOS:
        pending.pop(next(iter(pending)))


async def _read_and_preview(query, context, item: dict) -> None:
    kind, day = item["kind"]
    await query.edit_message_text("Okuyorum… ⏳")
    try:
        data = await schedule.read_photo(item["photo"], kind, _deps(context)["llm"])
    except Exception:
        log.exception("Program fotoğrafı okunamadı")
        await query.edit_message_text("Programı okuyamadım, daha net bir fotoğraf atar mısın?")
        return
    item["parsed"] = data
    existing = await _deps(context)["db"].get_schedule(kind, day)
    if existing:
        note = "Bu gün için kayıtlı program var. Yeni dersleri saatine göre ekleyebilir ya da eskisinin yerine koyabilirim."
        markup = MERGE_BUTTONS
    else:
        note = "Doğru mu?"
        markup = CONFIRM_BUTTONS
    await query.edit_message_text(f"Şunu okudum:\n\n{_format(kind, data)[:3500]}\n\n{note}", reply_markup=markup)


async def _read_note(query, context, item: dict) -> None:
    d = _deps(context)
    await query.edit_message_text("Notu okuyorum… ⏳")
    try:
        text = (await d["llm"].ask(NOTE_PROMPT, image=item["photo"], max_tokens=2000)).strip()
    except Exception:
        log.exception("Ders notu fotoğrafı okunamadı")
        await query.edit_message_text("Notu okuyamadım, daha net bir fotoğraf atar mısın?")
        return
    okul = await d["db"].get_schedule("okul", "")
    subjects: list[str] = []
    for lessons in (okul or {}).values():
        for lesson in lessons:
            if lesson["ders"] not in subjects:
                subjects.append(lesson["ders"])
    subjects = subjects[:12]
    item["note_text"] = text
    item["subjects"] = subjects
    buttons = [InlineKeyboardButton(s, callback_data=f"subj:{i}") for i, s in enumerate(subjects)]
    buttons.append(InlineKeyboardButton("Diğer", callback_data="subj:-1"))
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    await query.edit_message_text(f"Şunu okudum:\n\n{text[:1500]}\n\nHangi derse ait?", reply_markup=InlineKeyboardMarkup(rows))


async def _solve(update, query, context, item: dict) -> None:
    d = _deps(context)
    await query.edit_message_text("Soruyu okuyorum… ⏳")
    try:
        question = (await d["llm"].ask(SOLVE_OCR_PROMPT, image=item["photo"], max_tokens=1500)).strip()
        await query.edit_message_text("Çözüyorum… 🧠")
        answer = (await d["llm"].ask(f"Soru:\n{question}", SOLVE_SYSTEM, max_tokens=4000, reasoning="medium")).strip()
    except Exception:
        log.exception("Soru çözülemedi")
        await query.edit_message_text("Soruyu çözemedim, daha net bir fotoğraf atar mısın?")
        return
    await query.edit_message_text("✅ Çözüm aşağıda")
    await send_text(context.bot, update.effective_chat.id, f"❓ {question[:1000]}\n\n{answer}")


def _format(kind: str, data) -> str:
    return schedule.format_okul(data) if kind == "okul" else schedule.format_lessons(data)


def _merge(kind: str, old, new):
    return schedule.merge_okul(old, new) if kind == "okul" else schedule.merge_lessons(old, new)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    pending = context.user_data.setdefault("pending", {})
    item = pending.get(query.message.message_id)
    if item is None:
        await query.edit_message_text("Bu fotoğrafı artık bulamıyorum, tekrar atar mısın?")
        return
    if query.data == "pick:program":
        await query.edit_message_text("Bu hangi program?", reply_markup=KIND_BUTTONS)
    elif query.data == "pick:note":
        await _read_note(query, context, item)
    elif query.data == "pick:solve":
        await _solve(update, query, context, item)
        pending.pop(query.message.message_id, None)
    elif query.data.startswith("subj:") and "note_text" in item:
        index = int(query.data.split(":")[1])
        subject = item["subjects"][index] if 0 <= index < len(item["subjects"]) else None
        await _deps(context)["db"].add_note(item["note_text"], "foto", subject)
        pending.pop(query.message.message_id, None)
        label = f" ({subject})" if subject else ""
        await query.edit_message_text(f"📝 Not kaydedildi{label}:\n\n{item['note_text'][:3500]}")
    elif query.data.startswith("kind:"):
        _, kind, day = query.data.split(":")
        item["kind"] = (kind, day)
        await _read_and_preview(query, context, item)
    elif query.data == "retry" and "kind" in item:
        await _read_and_preview(query, context, item)
    elif query.data in ("save", "merge") and "parsed" in item:
        kind, day = item["kind"]
        db = _deps(context)["db"]
        old = await db.get_schedule(kind, day) if query.data == "merge" else None
        result = _merge(kind, old, item["parsed"])
        await db.save_schedule(kind, day, result)
        pending.pop(query.message.message_id, None)
        title = "➕ Mevcut programa eklendi, saatine göre sıralandı:" if query.data == "merge" else "✅ Program kaydedildi:"
        await query.edit_message_text(f"{title}\n\n{_format(kind, result)[:3800]}")


async def voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = _deps(context)
    file = await update.message.voice.get_file()
    audio = bytes(await file.download_as_bytearray())
    try:
        text = await d["transcriber"].transcribe(audio)
    except Exception:
        log.exception("Ses yazıya çevrilemedi")
        await update.message.reply_text("Sesi yazıya çeviremedim. Ses mesajın sohbette duruyor, bana tekrar iletebilirsin.")
        return
    kind = intents.route(text)
    if kind:
        await update.message.reply_text(f"🎤 {text}")
        if await handle_intent(update, context, text, kind):
            return
    await d["db"].add_note(text, "ses")
    await update.message.reply_text(f"📝 Kaydedildi: {text}")


async def _fire_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    reminder_id, text = context.job.data
    d = _deps(context)
    await context.bot.send_message(d["cfg"].owner_id, f"⏰ {text}")
    await d["db"].mark_sent(reminder_id)


def schedule_reminder(job_queue, reminder_id: int, when: datetime, text: str) -> None:
    job_queue.run_once(_fire_reminder, when=when, data=(reminder_id, text), name=f"rem-{reminder_id}")


async def restore_reminders(app: Application) -> None:
    d = app.bot_data
    now = datetime.now(d["cfg"].tz)
    for r in await d["db"].pending_reminders():
        if r["due_at"] <= now:
            await app.bot.send_message(d["cfg"].owner_id, f"⏰ (gecikmeli) {r['text']}")
            await d["db"].mark_sent(r["id"])
        else:
            schedule_reminder(app.job_queue, r["id"], r["due_at"], r["text"])


async def _create_reminder(update: Update, context, message: str) -> None:
    d = _deps(context)
    try:
        when, text = await reminders.parse(message, _now(context), d["llm"])
    except reminders.ReminderError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return
    except LLMError:
        log.exception("Hatırlatıcı LLM ile ayrıştırılamadı")
        await update.message.reply_text(LLM_DOWN)
        return
    reminder_id = await d["db"].add_reminder(text, when)
    schedule_reminder(context.job_queue, reminder_id, when, text)
    await update.message.reply_text(f"⏰ Tamam! {reminders.format_when(when)} — {text} (#{reminder_id})")


async def hatirlat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Kullanım: /hatirlat yarın 15'te faturayı öde")
        return
    await _create_reminder(update, context, " ".join(context.args))


async def hatirlaticilar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = _deps(context)
    pending = await d["db"].pending_reminders()
    if not pending:
        await update.message.reply_text("Bekleyen hatırlatıcı yok.")
        return
    lines = [f"#{r['id']} {reminders.format_when(r['due_at'].astimezone(d['cfg'].tz))} — {r['text']}" for r in pending]
    await send_text(context.bot, update.effective_chat.id, "\n".join(lines))


async def sil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not re.fullmatch(r"#?[0-9]+", context.args[0]):
        await update.message.reply_text("Kullanım: /sil 3")
        return
    reminder_id = int(context.args[0].lstrip("#"))
    for job in context.job_queue.get_jobs_by_name(f"rem-{reminder_id}"):
        job.schedule_removal()
    deleted = await _deps(context)["db"].delete_reminder(reminder_id)
    await update.message.reply_text("🗑 Silindi." if deleted else "Bu numarada hatırlatıcı yok.")


async def _create_task(update: Update, context, message: str) -> bool:
    d = _deps(context)
    today = _now(context).date()
    try:
        kind, title, due = await tasks.parse(message, today, d["llm"])
    except tasks.NotATask:
        return False
    except tasks.TaskError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return True
    except LLMError:
        log.exception("Ödev/sınav LLM ile ayrıştırılamadı")
        await update.message.reply_text(LLM_DOWN)
        return True
    task_id = await d["db"].add_task(kind, title, due)
    item = {"id": task_id, "kind": kind, "title": title, "due": due, "done": False}
    await update.message.reply_text(f"Kaydedildi: {tasks.format_task(item, today)}\nBitince /bitti {task_id} yaz.")
    return True


async def odevler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = _deps(context)
    items = await d["db"].list_tasks()
    await send_text(context.bot, update.effective_chat.id, tasks.format_tasks(items, _now(context).date()))


async def bitti(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not re.fullmatch(r"#?[0-9]+", context.args[0]):
        await update.message.reply_text("Kullanım: /bitti 3")
        return
    done = await _deps(context)["db"].set_task_done(int(context.args[0].lstrip("#")), True)
    await update.message.reply_text("✅ Tamamlandı olarak işaretlendi." if done else "Bu numarada ödev ya da sınav yok.")


async def _school_reply(update, coro, on_ok) -> bool:
    try:
        result = await coro
    except school.NotThis:
        return False
    except school.SchoolError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return True
    except LLMError:
        log.exception("Okul kaydı LLM ile ayrıştırılamadı")
        await update.message.reply_text(LLM_DOWN)
        return True
    await update.message.reply_text(await on_ok(result))
    return True


async def _create_grade(update, context, message: str) -> bool:
    d = _deps(context)

    async def saved(result):
        subject, label, score = result
        grade_id = await d["db"].add_grade(subject, label, score)
        return f"📊 Not kaydedildi: {subject} — {label}: {school.num(score)} (#{grade_id})\nOrtalamalar için /ortalama"

    return await _school_reply(update, school.parse_grade(message, d["llm"]), saved)


async def _create_absence(update, context, message: str) -> bool:
    d = _deps(context)

    async def saved(result):
        day, excused, half = result
        await d["db"].add_absence(day, excused, half)
        totals = school.absence_totals(await d["db"].list_absences())
        kind = ("özürlü" if excused else "özürsüz") + (", yarım gün" if half else "")
        return f"📅 Devamsızlık kaydedildi: {day:%d.%m.%Y} ({kind})\n{school.absence_status(totals)}"

    return await _school_reply(update, school.parse_absence(message, _now(context).date(), d["llm"]), saved)


async def _create_exam(update, context, message: str) -> bool:
    d = _deps(context)

    async def saved(result):
        kind, total, details = result
        await d["db"].add_exam(kind, total, details, _now(context).date())
        s = await load_settings(d)
        summary = school.exam_summary(await d["db"].list_exams(), kind, s.get(f"target_{kind.lower()}"))
        return f"🎯 {kind} denemesi kaydedildi: {school.num(total)} net" + (f"\n{summary}" if summary else "")

    return await _school_reply(update, school.parse_exam(message, d["llm"]), saved)


async def handle_intent(update, context, message: str, kind: str) -> bool:
    if kind == "reminder":
        await _create_reminder(update, context, message)
        return True
    handlers = {"task": _create_task, "grade": _create_grade, "absence": _create_absence, "exam": _create_exam}
    return await handlers[kind](update, context, message)


async def ortalama(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = _deps(context)
    subjects, overall = school.averages(await d["db"].list_grades(), school.subject_hours(await d["db"].get_schedule("okul", "")))
    await send_text(context.bot, update.effective_chat.id, school.format_grades(subjects, overall))


async def devamsizlik(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = await _deps(context)["db"].list_absences()
    lines = [school.absence_status(school.absence_totals(rows))]
    for r in rows[:10]:
        lines.append(f"• {r['day']:%d.%m.%Y} {'özürlü' if r['excused'] else 'özürsüz'}{' (yarım)' if r['half'] else ''}")
    await send_text(context.bot, update.effective_chat.id, "\n".join(lines))


async def yks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = _deps(context)
    s = await load_settings(d)
    today = _now(context).date()
    lines = [calendar_tr.school_line(today, date.fromisoformat(s["yks_date"]), s["yks_estimated"])]
    exams = await d["db"].list_exams()
    for kind in ("TYT", "AYT"):
        summary = school.exam_summary(exams, kind, s.get(f"target_{kind.lower()}"))
        if summary:
            lines.append(summary)
    if len(lines) == 1:
        lines.append('Deneme netlerini "tyt deneme 78 net" gibi yazarak ekleyebilirsin.')
    await send_text(context.bot, update.effective_chat.id, "\n\n".join(lines))


async def text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message.text
    kind = intents.route(message)
    if kind and await handle_intent(update, context, message, kind):
        return
    d = _deps(context)
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        reply = await chat.answer(message, d["db"], d["llm"], _now(context))
    except LLMError:
        log.exception("Sohbet cevabı alınamadı")
        await update.message.reply_text(LLM_DOWN)
        return
    await send_text(context.bot, update.effective_chat.id, reply)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, (Conflict, NetworkError)):
        log.warning("Telegram bağlantı/polling hatası: %s", context.error)
        return
    log.error("Beklenmeyen hata", exc_info=context.error)
    try:
        await context.bot.send_message(context.bot_data["cfg"].owner_id, f"⚠️ Bir hata oldu: {context.error}")
    except Exception:
        log.exception("Hata mesajı da gönderilemedi")


def register(app: Application) -> None:
    app.add_handler(TypeHandler(Update, gate), group=-1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CommandHandler("ozet", ozet))
    app.add_handler(CommandHandler("program", program))
    app.add_handler(CommandHandler("notlar", notlar))
    app.add_handler(CommandHandler("hatirlat", hatirlat))
    app.add_handler(CommandHandler("hatirlaticilar", hatirlaticilar))
    app.add_handler(CommandHandler("sil", sil))
    app.add_handler(CommandHandler("odevler", odevler))
    app.add_handler(CommandHandler("bitti", bitti))
    app.add_handler(CommandHandler("yks", yks))
    app.add_handler(CommandHandler("ortalama", ortalama))
    app.add_handler(CommandHandler("devamsizlik", devamsizlik))
    app.add_handler(MessageHandler(filters.PHOTO, photo))
    app.add_handler(MessageHandler(filters.VOICE, voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_error_handler(on_error)
