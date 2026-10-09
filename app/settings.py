import copy
import re
from datetime import date

SECTIONS = ["school", "weather", "lessons", "tasks", "finance", "news"]
DEFAULTS = {
    "briefing_time": "07:00",
    "sections": {s: True for s in SECTIONS},
    "photo_card": True,
    "news_count": 5,
    "evening_enabled": True,
    "evening_time": "23:00",
    "weather_alerts": True,
    "yks_date": "2027-06-19",
    "yks_estimated": True,
    "target_tyt": None,
    "target_ayt": None,
}
TARGET_MAX = {"target_tyt": 120, "target_ayt": 80}


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
    if not any(sections.values()):
        raise SettingsError("Özette en az bir bölüm açık olmalı")
    if not isinstance(payload.get("photo_card"), bool):
        raise SettingsError("Fotoğraf kartı açık/kapalı olmalı")
    count = payload.get("news_count")
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 10:
        raise SettingsError("Haber sayısı 1 ile 10 arasında olmalı")
    if not isinstance(payload.get("evening_enabled"), bool):
        raise SettingsError("Akşam özeti açık/kapalı olmalı")
    if payload["evening_enabled"] and not any(sections[s] for s in ("weather", "lessons", "tasks")):
        raise SettingsError("Akşam özeti için hava, ders ya da ödev bölümlerinden en az biri açık olmalı")
    for key in ("weather_alerts", "yks_estimated"):
        if not isinstance(payload.get(key), bool):
            raise SettingsError("Açık/kapalı ayarı hatalı")
    try:
        yks = date.fromisoformat(str(payload.get("yks_date"))).isoformat()
    except ValueError as e:
        raise SettingsError("YKS tarihi YYYY-AA-GG biçiminde olmalı") from e
    targets = {}
    for key, top in TARGET_MAX.items():
        value = payload.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= top):
            raise SettingsError(f"Hedef net 0 ile {top} arasında olmalı")
        targets[key] = value
    return {
        **targets,
        "weather_alerts": payload["weather_alerts"],
        "yks_date": yks,
        "yks_estimated": payload["yks_estimated"],
        "briefing_time": _time(payload.get("briefing_time")),
        "sections": dict(sections),
        "photo_card": payload["photo_card"],
        "news_count": count,
        "evening_enabled": payload["evening_enabled"],
        "evening_time": _time(payload.get("evening_time")),
    }
