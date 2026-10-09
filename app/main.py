import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from telegram.ext import Application

from app import bot, config
from app.db import DB
from app.llm import LLM
from app.notes import Transcriber

log = logging.getLogger(__name__)


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def start_health_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), _Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def _post_init(app: Application) -> None:
    cfg = app.bot_data["cfg"]
    http = httpx.AsyncClient(headers={"User-Agent": "gunluk-ajan/1.0"})
    app.bot_data["http"] = http
    app.bot_data["llm"] = LLM(cfg.llm_key, cfg.llm_base_url, cfg.llm_model, cfg.llm_vision_model, http=http)
    app.bot_data["db"] = await DB.connect(cfg.database_url)
    await bot.restore_reminders(app)
    log.info("Bot hazır")


async def _post_shutdown(app: Application) -> None:
    if "http" in app.bot_data:
        await app.bot_data["http"].aclose()
    if "db" in app.bot_data:
        await app.bot_data["db"].close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = config.load()
    start_health_server(cfg.port)
    app = (
        Application.builder()
        .token(cfg.telegram_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data.update(cfg=cfg, transcriber=Transcriber(cfg.groq_key))
    bot.register(app)
    app.run_polling()


if __name__ == "__main__":
    main()
