import re
import secrets
from datetime import datetime, timedelta

from app import news
from app.settings import SettingsError, _time, validate_topics

INVITE_TTL = timedelta(hours=24)
QUIET_START, QUIET_END = 0, 8
KUS_INTERVAL_SECONDS = 3600
EVENING_TIME = "23:00"

KUS = "😤 Boykot başlasın"
KUS_ALIASES = {KUS, "😤 Küstüm"}
BARIS = "🕊 Barıştık"
OZLEDIM = "🥺 Özledim"
YARDIM = "❓ Nasıl kullanılır"

DEFAULTS = {"briefing_time": "07:00", "evening_enabled": True, "news_topics": ["gundem", "yasam"]}
SELF_KEYS = set(DEFAULTS)


def new_invite(now: datetime) -> dict:
    return {"code": secrets.token_urlsafe(8), "expires": (now + INVITE_TTL).isoformat()}


def invite_valid(invite: dict | None, code: str, now: datetime) -> bool:
    if not invite or not code:
        return False
    return secrets.compare_digest(invite["code"], code) and now < datetime.fromisoformat(invite["expires"])


def new_partner(user_id: int, name: str) -> dict:
    return {"id": user_id, "name": (name or "Sevgilin").strip()[:40], **DEFAULTS}


def merge(stored: dict | None) -> dict | None:
    if not stored:
        return None
    return {**DEFAULTS, **stored, "news_topics": news.valid_topics(stored.get("news_topics")) or DEFAULTS["news_topics"]}


def validate_self(payload) -> dict:
    if not isinstance(payload, dict):
        raise SettingsError("Ayarlar bir nesne olmalı")
    if not isinstance(payload.get("evening_enabled"), bool):
        raise SettingsError("Akşam özeti açık/kapalı olmalı")
    return {
        "briefing_time": _time(payload.get("briefing_time")),
        "evening_enabled": payload["evening_enabled"],
        "news_topics": validate_topics(payload.get("news_topics")),
    }


def validate_owner(payload) -> dict:
    value = validate_self(payload)
    name = str(payload.get("name", "")).strip()
    if not name or len(name) > 40:
        raise SettingsError("İsim 1-40 karakter olmalı")
    return {**value, "name": name}


def is_quiet(now: datetime) -> bool:
    return QUIET_START <= now.hour < QUIET_END


def duration(since: datetime, now: datetime) -> str:
    minutes = max(int((now - since).total_seconds() // 60), 1)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = [f"{days} gün" if days else "", f"{hours} saat" if hours else "", f"{minutes} dakika" if minutes else ""]
    return " ".join(p for p in parts if p)


def _norm(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower()


def targets_partner(message: str, name: str | None) -> bool:
    if not name:
        return False
    first = re.escape(_norm(name.split()[0]))
    return re.search(rf"(?<!\w){first}['’]?(?:ya|ye|a|e)(?!\w)", _norm(message)) is not None


def keyboard_rows(kus: bool) -> list[list[str]]:
    return [[BARIS if kus else KUS, OZLEDIM], [YARDIM]]


def welcome(name: str) -> str:
    return (
        f"Merhaba {name}! 🌸 Ben Saha, Kayra seni buraya senin için ekledi.\n\n"
        "Nasıl kullanacağını hemen anlatayım 👇 İstediğin zaman alttaki "
        f"\"{YARDIM}\" butonuna basıp bu rehberi tekrar açabilirsin."
    )


def guide(name: str, briefing_time: str) -> str:
    return (
        f"📖 Saha rehberi\n\n"
        f"☀️ Sabah özeti — her sabah {briefing_time}'da gelir:\n"
        "• Hava durumu ve ne giysem önerisi\n"
        "• O günün dersleri\n"
        "• Seçtiğin konulardan haberler, her biri tek cümle\n"
        "• Kayra bir not bıraktıysa en altta 💌\n\n"
        "🌙 Gece 23:00 özeti: günün haberleri, yarının dersleri ve havası.\n\n"
        "⬇️ Alttaki butonlar:\n"
        f"• {KUS} — Kayra'ya anında 🚨 alarm gider; barışana kadar saatte bir hatırlatılır 😤\n"
        f"• {BARIS} — boykot biter, Kayra'ya ne kadar sürdüğü bildirilir\n"
        f"• {OZLEDIM} — Kayra'ya özlediğini iletirim\n\n"
        "⚙️ Panel (sol alttaki Panel düğmesi):\n"
        "• Hangi konularda haber geleceğini seç (gündem, yaşam, spor, sağlık…)\n"
        "• Sabah özeti saatini değiştir\n"
        "• Gece özetini aç/kapat\n"
        "Değiştirdikten sonra alttaki Kaydet'e basman yeterli.\n\n"
        f"Hepsi bu kadar {name} 💕"
    )
