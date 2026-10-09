import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update, WebAppInfo
from telegram.ext import (
    Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler,
    TypeHandler, filters,
)

from telegram.error import Conflict, NetworkError, TimedOut

from app import briefing, card, chat, reminders, schedule, settings, weather
from app.llm import LLMError
from app.textutil import split_message

log = logging.getLogger(__name__)

LLM_DOWN = "⚠️ Yapay zekâya şu an ulaşamıyorum, birazdan tekrar dener misin?"

HELP = (
    "Merhaba Kayra, ben Saha! Yapabileceklerim:\n"
    "📷 Ders programı fotoğrafı at → kaydederim\n"
    "🎤 Sesli mesaj at → nota çeviririm\n"
    "⏰ \"yarın 15'te faturayı hatırlat\" yaz → hatırlatırım\n"
    "💬 Başka bir şey yaz → notlarına ve programına bakarak cevaplarım\n\n"
    "/panel ayarlar ve program paneli\n"
    "/ozet sabah özetini şimdi gönder\n"
    "/program kayıtlı programlar\n"
    "/notlar son notlar\n"
    "/hatirlat <metin>\n"
    "/hatirlaticilar bekleyen hatırlatıcılar\n"
    "/sil <id> hatırlatıcıyı sil"
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


async def build_briefing(bot_data, today) -> tuple[briefing.Briefing, dict]:
    s = await load_settings(bot_data)
    src = briefing.make_sources(bot_data["cfg"], bot_data["db"], bot_data["llm"], bot_data["http"], today, s)
    return await briefing.build(today, src, s), s


def photo_caption(info: briefing.WeatherInfo) -> str:
    return f"🌤 Buca — {weather.summary(info.w)}\n👕 {info.advice}"[:1024]


def next_briefing_day(now: datetime, briefing_time: str) -> date:
    hour, minute = map(int, briefing_time.split(":"))
    return now.date() if (now.hour, now.minute) < (hour, minute) else now.date() + timedelta(days=1)


async def send_briefing(context: ContextTypes.DEFAULT_TYPE, day: date | None = None) -> None:
    d = _deps(context)
    owner = d["cfg"].owner_id
    today = day or _now(context).date()
    result, s = await build_briefing(d, today)
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
    sent = await update.message.reply_text("Bu hangi program?", reply_markup=KIND_BUTTONS)
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
    if query.data.startswith("kind:"):
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
    if not context.args or not context.args[0].lstrip("#").isdigit():
        await update.message.reply_text("Kullanım: /sil 3")
        return
    reminder_id = int(context.args[0].lstrip("#"))
    for job in context.job_queue.get_jobs_by_name(f"rem-{reminder_id}"):
        job.schedule_removal()
    deleted = await _deps(context)["db"].delete_reminder(reminder_id)
    await update.message.reply_text("🗑 Silindi." if deleted else "Bu numarada hatırlatıcı yok.")


async def text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message.text
    if is_reminder_request(message):
        await _create_reminder(update, context, message)
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
    app.add_handler(MessageHandler(filters.PHOTO, photo))
    app.add_handler(MessageHandler(filters.VOICE, voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_error_handler(on_error)
