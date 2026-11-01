import re
from datetime import date

from app.schedule import ALL_DAYS

TURLER = ("yazılı", "sözlü", "deneme", "uygulama")
VARSAYILAN_TUR = "yazılı"
TUR_ADI = {"yazılı": "yazılısı", "sözlü": "sözlüsü", "deneme": "denemesi", "uygulama": "uygulaması"}
BRANCH_KEY = "exam_branch"
PROMPT = (
    "Bu bir okul sınav takvimi fotoğrafı. Sadece JSON döndür, başka bir şey yazma. Biçim: "
    '{"siniflar": ["12 Say", "12 EA"], "sinavlar": [{"sinif": "12 Say", "tarih": "2026-11-10", '
    '"saat": "09:40", "ders": "Matematik", "tur": "yazılı"}]}. '
    "siniflar: fotoğrafta görünen şube/sınıf adları (12 Say, 11-B gibi), aynen yaz. "
    "sinavlar: her satır ayrı bir sınav. sinif alanına o sınavın hangi şubeye ait olduğunu yaz; "
    "sınav bütün şubeler için ortaksa boş string bırak. "
    "tarih YYYY-AA-GG biçiminde (fotoğrafta yıl yoksa {yil} varsay). "
    "saat HH:MM biçiminde; saat yoksa boş string. "
    "tur: yazılı, sözlü, deneme ya da uygulama; yazmıyorsa yazılı. "
    "Okunamayan alanı boş bırak, uydurma. Sınav yoksa sinavlar: [] döndür."
)
TEXT_SYSTEM = (
    "Kullanıcının yazdığı sınav kaydını ayrıştır. Sadece JSON döndür: "
    '{"ders": "Matematik", "tarih": "YYYY-AA-GG", "saat": "HH:MM", "tur": "yazılı"}. '
    "'cuma', 'yarın', '20 kasım', 'gelecek hafta salı' gibi ifadeleri verilen bugüne göre çöz; "
    "gün adı verilmişse bugünden sonraki ilk o günü seç. Saat yoksa boş string, tur yazılmadıysa yazılı yaz. "
    'Mesaj yeni bir sınav kaydı değilse {"ders": null} döndür.'
)


class ExamCalError(ValueError):
    pass


class NotAnExam(Exception):
    pass


def _normalize(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower().strip()


def _saat(value) -> str:
    m = re.search(r"(\d{1,2})[:.](\d{2})", str(value or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return ""
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _tur(value) -> str:
    t = _normalize(str(value or ""))
    if not t:
        return VARSAYILAN_TUR
    for known in TURLER:
        if known in t:
            return known
    return t[:24]


def _tarih(value, today: date) -> date:
    text = str(value or "").strip()
    try:
        day = date.fromisoformat(text)
    except ValueError:
        m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?", text)
        if not m:
            raise ExamCalError(f"Tarihi anlayamadım: {text or 'boş'}")
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            day = date(year, month, day)
        except ValueError as e:
            raise ExamCalError(f"Geçersiz tarih: {text}") from e
    if (today - day).days > 180:
        try:
            day = day.replace(year=day.year + 1)
        except ValueError:
            pass
    return day


def _exam(item, today: date) -> dict:
    if not isinstance(item, dict):
        raise ExamCalError(f"Geçersiz sınav kaydı: {item}")
    subject = str(item.get("ders", item.get("subject", ""))).strip()
    if not subject:
        raise ExamCalError(f"Geçersiz sınav kaydı: {item}")
    return {
        "subject": subject[:80],
        "day": _tarih(item.get("tarih", item.get("day")), today),
        "at_time": _saat(item.get("saat", item.get("at_time"))),
        "kind": _tur(item.get("tur", item.get("kind"))),
        "branch": str(item.get("sinif", item.get("branch", ""))).strip()[:24],
    }


def parse_result(data, today: date) -> tuple[list[str], list[dict]]:
    if isinstance(data, list):
        data = {"sinavlar": data}
    if not isinstance(data, dict):
        raise ExamCalError("Sınav takvimi çözümlenemedi")
    raw = data.get("sinavlar")
    if raw is None:
        raw = data.get("exams")
    if not isinstance(raw, list):
        raise ExamCalError("Sınav listesi bekleniyordu")
    exams = [_exam(item, today) for item in raw]
    if not exams:
        raise ExamCalError("Sınav takviminde sınav bulunamadı")
    branches: list[str] = []
    for name in data.get("siniflar") or []:
        name = str(name).strip()[:24]
        if name and name not in branches:
            branches.append(name)
    for exam in exams:
        if exam["branch"] and exam["branch"] not in branches:
            branches.append(exam["branch"])
    return branches, exams


async def read_photo(image: bytes, llm, today: date) -> tuple[list[str], list[dict]]:
    data = await llm.ask_json(PROMPT.replace("{yil}", str(today.year)), image=image)
    return parse_result(data, today)


def parse_text_result(data, today: date) -> dict:
    if isinstance(data, dict) and "ders" in data and data["ders"] is None:
        raise NotAnExam
    if isinstance(data, dict) and not data.get("ders") and not data.get("subject"):
        raise NotAnExam
    return _exam(data, today)


async def parse_text(message: str, today: date, llm) -> dict:
    prompt = f"Bugün: {today:%Y-%m-%d} ({ALL_DAYS[today.weekday()]}). Kayıt: {message}"
    return parse_text_result(await llm.ask_json(prompt, TEXT_SYSTEM), today)


def branches(exams: list[dict]) -> list[str]:
    out: list[str] = []
    for exam in exams:
        if exam.get("branch") and exam["branch"] not in out:
            out.append(exam["branch"])
    return out


def filter_branch(exams: list[dict], branch: str | None) -> list[dict]:
    if not branch:
        return list(exams)
    return [e for e in exams if not e.get("branch") or e["branch"] == branch]


def future_only(exams: list[dict], today: date, grace: int = 1) -> list[dict]:
    return [e for e in exams if (today - e["day"]).days <= grace]


def _sort_key(exam: dict):
    minutes = None
    if exam.get("at_time"):
        hour, minute = exam["at_time"].split(":")
        minutes = int(hour) * 60 + int(minute)
    return (exam["day"], 0 if minutes is not None else 1, minutes or 0, exam["subject"].casefold())


def merge(old: list[dict], new: list[dict]) -> list[dict]:
    combined = list(old or [])
    seen = {(e["day"], e["subject"].casefold(), e.get("at_time", "")) for e in combined}
    for exam in new:
        key = (exam["day"], exam["subject"].casefold(), exam.get("at_time", ""))
        if key not in seen:
            combined.append(exam)
            seen.add(key)
    return sorted(combined, key=_sort_key)


def plan_add(existing: list[dict], new: list[dict]) -> list[dict]:
    seen = {(e["day"], e["subject"].casefold(), e.get("at_time", "")) for e in existing or []}
    out = []
    for exam in new:
        key = (exam["day"], exam["subject"].casefold(), exam.get("at_time", ""))
        if key not in seen:
            out.append(exam)
            seen.add(key)
    return sorted(out, key=_sort_key)


def relative(day: date, today: date) -> str:
    diff = (day - today).days
    if diff == 0:
        return "bugün"
    if diff == 1:
        return "yarın"
    if diff > 1:
        return f"{diff} gün sonra"
    return f"{-diff} gün önce"


def _saat_eki(exam: dict) -> str:
    return f" {exam['at_time']}" if exam.get("at_time") else ""


def tur_adi(exam: dict) -> str:
    return TUR_ADI.get(exam["kind"], exam["kind"])


def format_brief(exam: dict, today: date) -> str:
    icon = "🎯" if exam["kind"] == "deneme" else "🧪"
    return f"{icon} {relative(exam['day'], today)}: {exam['subject']} {tur_adi(exam)} ({exam['day']:%d.%m}{_saat_eki(exam)})"


def format_exam(exam: dict, today: date) -> str:
    icon = "🎯" if exam["kind"] == "deneme" else "🧪"
    branch = f" · {exam['branch']}" if exam.get("branch") else ""
    rid = f" #{exam['id']}" if exam.get("id") else ""
    return (
        f"{icon} {exam['day']:%d.%m} {ALL_DAYS[exam['day'].weekday()]}{_saat_eki(exam)} — "
        f"{exam['subject']} {tur_adi(exam)}{branch} ({relative(exam['day'], today)}){rid}"
    )


def format_preview(exams: list[dict], today: date) -> str:
    if not exams:
        return "Sınav bulunamadı."
    return "\n".join(
        f"• {exam['day']:%d.%m} {ALL_DAYS[exam['day'].weekday()]}{_saat_eki(exam)} — {exam['subject']} {tur_adi(exam)}"
        for exam in exams
    )


def format_upcoming(exams: list[dict], today: date, days: int = 14) -> str:
    soon = sorted(
        (e for e in exams or [] if 0 <= (e["day"] - today).days <= days),
        key=_sort_key,
    )
    if not soon:
        return "Yaklaşan sınav yok 🎉"
    return "\n".join(format_brief(e, today) for e in soon)


def format_all(exams: list[dict], today: date) -> str:
    items = sorted(exams or [], key=_sort_key)
    upcoming = [e for e in items if e["day"] >= today]
    past = [e for e in items if e["day"] < today][-5:]
    parts = []
    if upcoming:
        parts.append("🧪 Yaklaşan sınavlar\n" + "\n".join(format_exam(e, today) for e in upcoming))
    else:
        parts.append("Yaklaşan sınav yok 🎉")
    if past:
        parts.append("🗄 Geçmiş\n" + "\n".join(format_exam(e, today) for e in past))
    parts.append("Yeni sınav takvimi fotoğrafı atarsan hepsini birden eklerim.")
    return "\n\n".join(parts)
