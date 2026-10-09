import copy
import re

SECTIONS = ["weather", "lessons", "finance", "news"]
DEFAULTS = {
    "briefing_time": "07:00",
    "sections": {s: True for s in SECTIONS},
    "photo_card": True,
    "news_count": 5,
}


class SettingsError(ValueError):
    pass


def merge(stored: dict | None, base_time: str) -> dict:
    result = copy.deepcopy(DEFAULTS)
    result["briefing_time"] = base_time
    for key, value in (stored or {}).items():
        if key == "sections" and isinstance(value, dict):
            result["sections"].update({k: v for k, v in value.items() if k in SECTIONS})
        elif key in DEFAULTS:
            result[key] = value
    return result


def _time(value) -> str:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value).strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise SettingsError("Saat SS:DD biçiminde olmalı (örn. 07:00)")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def validate(payload) -> dict:
    if not isinstance(payload, dict):
        raise SettingsError("Ayarlar bir nesne olmalı")
    unknown = set(payload) - set(DEFAULTS)
    if unknown:
        raise SettingsError(f"Bilinmeyen ayar: {', '.join(sorted(unknown))}")
    sections = payload.get("sections")
    if not isinstance(sections, dict) or set(sections) != set(SECTIONS) or not all(isinstance(v, bool) for v in sections.values()):
        raise SettingsError("Bölümler eksik ya da hatalı")
    if not isinstance(payload.get("photo_card"), bool):
        raise SettingsError("Fotoğraf kartı açık/kapalı olmalı")
    count = payload.get("news_count")
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 10:
        raise SettingsError("Haber sayısı 1 ile 10 arasında olmalı")
    return {
        "briefing_time": _time(payload.get("briefing_time")),
        "sections": dict(sections),
        "photo_card": payload["photo_card"],
        "news_count": count,
    }
