import re
from datetime import date

WEEKDAYS = ["pazartesi", "salı", "çarşamba", "perşembe", "cuma"]
WEEKEND = ["cumartesi", "pazar"]
ALL_DAYS = WEEKDAYS + WEEKEND

OKUL_PROMPT = (
    "Bu bir haftalık okul ders programı fotoğrafı. Sadece JSON döndür, başka bir şey yazma. Biçim: "
    '{"pazartesi": [{"saat": "08:30", "ders": "Matematik"}], "salı": [], "çarşamba": [], "perşembe": [], "cuma": []}. '
    "Ders sırasını koru. Saati görünüyorsa başlangıç-bitiş olarak yaz (örn. 08:30-09:10), sadece başlangıç varsa onu yaz, okunamıyorsa boş string. Boş günler için boş liste ver."
)
DERSHANE_PROMPT = (
    "Bu tek bir günün dershane ders programı fotoğrafı. Sadece JSON dizi döndür, başka bir şey yazma. Biçim: "
    '[{"saat": "13:30-15:10", "ders": "Fizik"}]. Ders sırasını koru. Saati görünüyorsa başlangıç-bitiş olarak yaz, sadece başlangıç varsa onu yaz, okunamıyorsa boş string.'
)


class ScheduleError(ValueError):
    pass


def _lessons(items) -> list[dict]:
    if not isinstance(items, list):
        raise ScheduleError("Ders listesi bekleniyordu")
    out = []
    for item in items:
        if not isinstance(item, dict) or not str(item.get("ders", "")).strip():
            raise ScheduleError(f"Geçersiz ders kaydı: {item}")
        out.append({"saat": str(item.get("saat", "")).strip(), "ders": str(item["ders"]).strip()})
    return out


def validate_okul(data) -> dict[str, list[dict]]:
    if not isinstance(data, dict):
        raise ScheduleError("Okul programı gün → ders listesi biçiminde olmalı")
    result = {d: _lessons(data.get(d, [])) for d in WEEKDAYS}
    if not any(result.values()):
        raise ScheduleError("Programda hiç ders bulunamadı")
    return result


def validate_dershane(data) -> list[dict]:
    lessons = _lessons(data)
    if not lessons:
        raise ScheduleError("Programda hiç ders bulunamadı")
    return lessons


async def read_photo(image: bytes, kind: str, llm):
    if kind == "okul":
        return validate_okul(await llm.ask_json(OKUL_PROMPT, image=image))
    return validate_dershane(await llm.ask_json(DERSHANE_PROMPT, image=image))


def start_minutes(saat: str) -> int | None:
    m = re.search(r"(\d{1,2})[:.](\d{2})", saat or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def merge_lessons(old, new) -> list[dict]:
    combined = list(old or [])
    seen = {(l["saat"], l["ders"].casefold()) for l in combined}
    for lesson in new:
        if (lesson["saat"], lesson["ders"].casefold()) not in seen:
            combined.append(lesson)
            seen.add((lesson["saat"], lesson["ders"].casefold()))
    order = {id(l): i for i, l in enumerate(combined)}

    def key(lesson):
        minutes = start_minutes(lesson["saat"])
        return (0, minutes, order[id(lesson)]) if minutes is not None else (1, 0, order[id(lesson)])

    return sorted(combined, key=key)


def merge_okul(old, new: dict) -> dict:
    return {d: merge_lessons((old or {}).get(d, []), new.get(d, [])) for d in WEEKDAYS}


def day_key(d: date) -> str:
    return ALL_DAYS[d.weekday()]


async def lessons_for(d: date, db):
    key = day_key(d)
    if key in WEEKDAYS:
        okul = await db.get_schedule("okul", "")
        return None if okul is None else okul.get(key, [])
    return await db.get_schedule("dershane", key)


def format_lessons(lessons) -> str:
    if lessons is None:
        return "Bu gün için kayıtlı program yok. Fotoğrafını atarsan kaydederim."
    if not lessons:
        return "Bugün ders yok 🎉"
    return "\n".join(f"• {l['saat'] + ' ' if l['saat'] else ''}{l['ders']}" for l in lessons)


def format_okul(data: dict) -> str:
    return "\n".join(f"{d.capitalize()}:\n{format_lessons(data.get(d, []))}" for d in WEEKDAYS)


def format_all(schedules: dict) -> str:
    okul = schedules.get("okul")
    parts = ["🏫 Okul (hafta içi)", format_okul(okul) if okul is not None else "Kayıtlı değil"]
    for d in WEEKEND:
        parts.append(f"📘 Dershane {d.capitalize()}:\n{format_lessons(schedules.get(d))}")
    return "\n".join(parts)
