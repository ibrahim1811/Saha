import re

from app import tasks

DATE_WORDS = re.compile(
    r"yarın|bugün|haftaya|pazartesi|salı|çarşamba|perşembe|cuma|cumartesi|pazar|"
    r"ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık"
)
GRADE_WORDS = re.compile(r"yazılı|performans|sözlü|proje notu|notum|notu\b")
ABSENCE_WORDS = re.compile(r"devamsız|okula gitmedim|okula gidemedim|raporlu|okulu kırdım|okulu astım")
SCORE_TAKEN = re.compile(r"\d+(?:[.,]\d+)?\s*(?:aldım|aldim|aldık)")


def normalize(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower().strip()


def route(text: str) -> str | None:
    t = normalize(text)
    if t.endswith("?"):
        return None
    if "hatırlat" in t:
        return "reminder"
    if "deneme" in t and ("net" in t or re.search(r"\d", t)):
        return "exam"
    if ABSENCE_WORDS.search(t):
        return "absence"
    if SCORE_TAKEN.search(t):
        return "grade"
    if GRADE_WORDS.search(t) and re.search(r"\d", t):
        return "task" if DATE_WORDS.search(t) else "grade"
    if tasks.is_task_request(text) or ("yazılı" in t and DATE_WORDS.search(t)):
        return "task"
    return None
