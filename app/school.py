from datetime import date

from app.schedule import ALL_DAYS

GRADE_SYSTEM = (
    "Kullanıcının yazdığı okul notu kaydını ayrıştır. Sadece JSON döndür: "
    '{"subject": "ders adı (örn. Fizik)", "label": "not türü (örn. 1. yazılı, performans)", "score": 0-100 arası sayı}. '
    'Bu yeni bir not kaydı değilse sadece {"subject": null} döndür.'
)
ABSENCE_SYSTEM = (
    "Kullanıcının devamsızlık bildirimini ayrıştır. Sadece JSON döndür: "
    '{"day": "YYYY-MM-DD", "excused": true/false, "half": true/false}. "bugün", "dün" ve gün adlarını verilen bugüne göre çöz. '
    "Rapor, izin ya da özürlü geçerse excused true; yarım gün geçerse half true. "
    'Bu yeni bir devamsızlık bildirimi değilse sadece {"day": null} döndür.'
)
EXAM_SYSTEM = (
    "Kullanıcının deneme sınavı netini ayrıştır. Sadece JSON döndür: "
    '{"kind": "TYT" ya da "AYT", "total": toplam net ya da null, "details": {"Türkçe": 32, "Matematik": 28}}. '
    "Tür belirtilmemişse TYT kabul et. Toplam yazılmamışsa null bırak. "
    'Bu yeni bir deneme kaydı değilse sadece {"kind": null} döndür.'
)
EXAM_MAX = {"TYT": 120, "AYT": 80}
UNEXCUSED_LIMIT = 10
TOTAL_LIMIT = 30


class SchoolError(ValueError):
    pass


class NotThis(Exception):
    pass


def num(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def parse_grade_result(data) -> tuple[str, str, float]:
    if isinstance(data, dict) and "subject" in data and data["subject"] is None:
        raise NotThis
    try:
        subject = str(data["subject"]).strip()
        label = str(data.get("label") or "not").strip()
        score = float(data["score"])
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise SchoolError('Notu anlayamadım, örneğin "fizik 1. yazılı 85" diye yazar mısın?') from e
    if not subject:
        raise SchoolError("Hangi derse ait olduğunu anlayamadım")
    if not 0 <= score <= 100:
        raise SchoolError("Not 0 ile 100 arasında olmalı")
    return subject, label, score


async def parse_grade(message: str, llm) -> tuple[str, str, float]:
    return parse_grade_result(await llm.ask_json(f"Kayıt: {message}", GRADE_SYSTEM))


def subject_hours(okul: dict | None) -> dict[str, int]:
    hours: dict[str, int] = {}
    for lessons in (okul or {}).values():
        for lesson in lessons:
            key = lesson["ders"].strip().casefold()
            hours[key] = hours.get(key, 0) + 1
    return hours


def averages(grades: list[dict], hours: dict[str, int]) -> tuple[list[dict], float | None]:
    groups: dict[str, dict] = {}
    for g in grades:
        key = g["subject"].strip().casefold()
        group = groups.setdefault(key, {"subject": g["subject"].strip(), "items": []})
        group["items"].append(g)
    subjects = []
    for key, group in sorted(groups.items()):
        scores = [float(i["score"]) for i in group["items"]]
        subjects.append({
            "subject": group["subject"],
            "average": round(sum(scores) / len(scores), 2),
            "hours": hours.get(key, 1),
            "items": group["items"],
        })
    if not subjects:
        return [], None
    weight = sum(s["hours"] for s in subjects)
    return subjects, sum(s["average"] * s["hours"] for s in subjects) / weight


def format_grades(subjects: list[dict], overall: float | None) -> str:
    if not subjects:
        return 'Henüz not yok. "fizik 1. yazılı 85" gibi yazarak ekleyebilirsin.'
    lines = [f"• {s['subject']}: {num(s['average'])} ({', '.join(num(float(i['score'])) for i in s['items'])})" for s in subjects]
    lines.append("")
    lines.append(f"📊 Ağırlıklı ortalama: {num(overall)}")
    return "\n".join(lines)


def parse_absence_result(data, today: date) -> tuple[date, bool, bool]:
    if isinstance(data, dict) and "day" in data and data["day"] is None:
        raise NotThis
    try:
        day = date.fromisoformat(str(data["day"]))
        excused = bool(data.get("excused", False))
        half = bool(data.get("half", False))
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise SchoolError("Hangi gün devamsızlık yaptığını anlayamadım") from e
    if day > today:
        raise SchoolError("İleri bir tarihe devamsızlık yazılamaz")
    return day, excused, half


async def parse_absence(message: str, today: date, llm) -> tuple[date, bool, bool]:
    prompt = f"Bugün: {today:%Y-%m-%d} ({ALL_DAYS[today.weekday()]}). Bildirim: {message}"
    return parse_absence_result(await llm.ask_json(prompt, ABSENCE_SYSTEM), today)


def school_year_rows(rows: list[dict], today: date) -> list[dict]:
    start = date(today.year if today.month >= 9 else today.year - 1, 9, 1)
    end = date(start.year + 1, 8, 31)
    return [r for r in rows if start <= r["day"] <= end]


def absence_totals(rows: list[dict]) -> dict[str, float]:
    unexcused = sum(0.5 if r["half"] else 1.0 for r in rows if not r["excused"])
    excused = sum(0.5 if r["half"] else 1.0 for r in rows if r["excused"])
    return {"unexcused": unexcused, "excused": excused, "total": unexcused + excused}


def absence_status(t: dict[str, float]) -> str:
    text = f"Özürsüz {num(t['unexcused'])}/{UNEXCUSED_LIMIT} gün, toplam {num(t['total'])}/{TOTAL_LIMIT} gün"
    if t["unexcused"] >= UNEXCUSED_LIMIT - 2 or t["total"] >= TOTAL_LIMIT - 5:
        text += "\n⚠️ Sınıra yaklaştın, dikkat et!"
    return text


def parse_exam_result(data) -> tuple[str, float, dict]:
    if isinstance(data, dict) and "kind" in data and data["kind"] is None:
        raise NotThis
    try:
        kind = str(data["kind"]).upper()
        details = {str(k).strip(): float(v) for k, v in (data.get("details") or {}).items()}
        total = data.get("total")
        total = float(total) if total is not None else (sum(details.values()) if details else None)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise SchoolError('Deneme netini anlayamadım, örneğin "tyt deneme 78 net"') from e
    if kind not in EXAM_MAX:
        raise SchoolError("Deneme türü TYT ya da AYT olmalı")
    if total is None:
        raise SchoolError("Toplam neti anlayamadım")
    if not 0 <= total <= EXAM_MAX[kind]:
        raise SchoolError(f"{kind} neti 0 ile {EXAM_MAX[kind]} arasında olmalı")
    return kind, total, details


async def parse_exam(message: str, llm) -> tuple[str, float, dict]:
    return parse_exam_result(await llm.ask_json(f"Kayıt: {message}", EXAM_SYSTEM))


def exam_summary(exams: list[dict], kind: str, target: float | None) -> str | None:
    items = sorted((e for e in exams if e["kind"] == kind), key=lambda e: e["taken"])
    if not items:
        return None
    last3 = [float(e["total"]) for e in items[-3:]]
    avg = sum(last3) / len(last3)
    lines = [f"{kind} — Son deneme: {num(float(items[-1]['total']))} net, Son {len(last3)} ortalama: {num(avg)} net"]
    if target:
        gap = target - avg
        lines.append(f"Hedefe {num(gap)} net var" if gap > 0 else "Hedefin üzerindesin 💪")
    return "\n".join(lines)
