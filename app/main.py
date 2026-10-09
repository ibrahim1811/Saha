import logging

import httpx
from telegram.ext import Application

from app import bot, config, status
from app.db import DB
from app.llm import LLM
from app.notes import Transcriber
from app.web import start_web

log = logging.getLogger(__name__)


async def _post_init(app: Application) -> None:
    cfg = app.bot_data["cfg"]
    http = httpx.AsyncClient(headers={"User-Agent": "gunluk-ajan/1.0"})
    app.bot_data["http"] = http
    app.bot_data["llm"] = LLM(cfg.llm_key, cfg.llm_base_url, cfg.llm_model, cfg.llm_vision_model, http=http)
    app.bot_data["db"] = await DB.connect(cfg.database_url)
    app.bot_data["web"] = await start_web(app, cfg.port)
    await bot.restore_reminders(app)
    s = await bot.load_settings(app.bot_data)
    bot.reschedule_briefing(app.job_queue, s["briefing_time"], cfg.tz)
    bot.reschedule_evening(app.job_queue, s, cfg.tz)
    bot.schedule_keep_alive(app.job_queue, cfg.public_url)
    try:
        await bot.setup_menu(app)
    except Exception:
        log.exception("Telegram menü düğmesi kurulamadı")
    log.info("Bot hazır (panel: %s)", cfg.public_url or "yerel")


async def _post_shutdown(app: Application) -> None:
    if "web" in app.bot_data:
        await app.bot_data["web"].cleanup()
    if "http" in app.bot_data:
        await app.bot_data["http"].aclose()
    if "db" in app.bot_data:
        await app.bot_data["db"].close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    errors = status.install()
    cfg = config.load()
    app = (
        Application.builder()
        .token(cfg.telegram_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data.update(cfg=cfg, transcriber=Transcriber(cfg.groq_key), errors=errors)
    bot.register(app)
    app.run_polling()


if __name__ == "__main__":
    main()
