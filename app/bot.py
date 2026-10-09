import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update, WebAppInfo
from telegram.ext import (
    Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler,
    TypeHandler, filters,
)

from telegram.error import Conflict, NetworkError

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


async def send_briefing(context: ContextTypes.DEFAULT_TYPE) -> None:
    d = _deps(context)
    owner = d["cfg"].owner_id
    today = _now(context).date()
    result, s = await build_briefing(d, today)
    if s["photo_card"] and result.weather:
        try:
            png = card.render_card(result.weather.w, result.weather.hints, today)
            await context.bot.send_photo(owner, png, caption=photo_caption(result.weather))
        except Exception:
            log.exception("Hava kartı gönderilemedi, metne dönülüyor")
        else:
            await send_text(context.bot, owner, result.text_without_weather)
            return
    await send_text(context.bot, owner, result.text)


async def ozet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_briefing(context)


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
    context.user_data["photo"] = bytes(await file.download_as_bytearray())
    await update.message.reply_text("Bu hangi program?", reply_markup=KIND_BUTTONS)


async def _read_and_preview(query, context) -> None:
    kind, day = context.user_data["kind"]
    await query.edit_message_text("Okuyorum… ⏳")
    try:
        data = await schedule.read_photo(context.user_data["photo"], kind, _deps(context)["llm"])
    except Exception:
        log.exception("Program fotoğrafı okunamadı")
        await query.edit_message_text("Programı okuyamadım, daha net bir fotoğraf atar mısın?")
        return
    context.user_data["parsed"] = data
    preview = schedule.format_okul(data) if kind == "okul" else schedule.format_lessons(data)
    await query.edit_message_text(f"Şunu okudum:\n\n{preview[:3800]}\n\nDoğru mu?", reply_markup=CONFIRM_BUTTONS)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if "photo" not in context.user_data:
        await query.edit_message_text("Fotoğraf bulunamadı, tekrar atar mısın?")
        return
    if query.data.startswith("kind:"):
        _, kind, day = query.data.split(":")
        context.user_data["kind"] = (kind, day)
        await _read_and_preview(query, context)
    elif query.data == "retry":
        await _read_and_preview(query, context)
    elif query.data == "save":
        kind, day = context.user_data["kind"]
        await _deps(context)["db"].save_schedule(kind, day, context.user_data["parsed"])
        context.user_data.clear()
        await query.edit_message_text("✅ Program kaydedildi.")


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
    if "hatırlat" in message.lower():
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
