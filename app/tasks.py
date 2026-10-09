from datetime import date

from app.schedule import ALL_DAYS

KINDS = {"odev": ("📝", "Ödev"), "sinav": ("🧪", "Sınav")}
SYSTEM = (
    "Kullanıcının yazdığı ödev ya da sınav kaydını ayrıştır. Sadece JSON döndür: "
    '{"kind": "odev" ya da "sinav", "title": "kısa başlık (örn. Fizik ödevi, Matematik sınavı)", "due": "YYYY-MM-DD"}. '
    "'cuma', 'yarın', '20 ekim', 'haftaya salı' gibi ifadeleri verilen bugünün tarihine göre çöz. "
    "Gün adı verilmişse bugünden sonraki ilk o günü seç."
)


class TaskError(ValueError):
    pass


def _normalize(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower().strip()


def is_task_request(text: str) -> bool:
    t = _normalize(text)
    if t.endswith("?") or "hatırlat" in t:
        return False
    return "ödev" in t or "sınav" in t


def parse_result(data, today: date) -> tuple[str, str, date]:
    try:
        kind = data["kind"]
        title = str(data["title"]).strip()
        due = date.fromisoformat(str(data["due"]))
    except (KeyError, TypeError, ValueError) as e:
        raise TaskError("Ödevi ya da sınavı anlayamadım, tarihiyle birlikte yazar mısın?") from e
    if kind not in KINDS:
        raise TaskError("Bunun ödev mi sınav mı olduğunu anlayamadım")
    if not title:
        raise TaskError("Başlığı anlayamadım")
    if due < today:
        raise TaskError(f"Bu tarih geçmişte: {due:%d.%m.%Y}")
    return kind, title, due


async def parse(message: str, today: date, llm) -> tuple[str, str, date]:
    prompt = f"Bugün: {today:%Y-%m-%d} ({ALL_DAYS[today.weekday()]}). Kayıt: {message}"
    return parse_result(await llm.ask_json(prompt, SYSTEM), today)


def relative(due: date, today: date) -> str:
    diff = (due - today).days
    if diff == 0:
        return "bugün"
    if diff == 1:
        return "yarın"
    if diff > 1:
        return f"{diff} gün sonra"
    return f"{-diff} gün geçti"


def format_task(task: dict, today: date) -> str:
    icon, _ = KINDS.get(task["kind"], ("📝", ""))
    if task.get("done"):
        icon = "✅"
    due = task["due"]
    return f"{icon} {task['title']} — {due.day}.{due.month:02d} {ALL_DAYS[due.weekday()]} ({relative(due, today)}) #{task['id']}"


def format_tasks(tasks: list[dict], today: date) -> str:
    if not tasks:
        return "Yaklaşan ödev ya da sınav yok."
    return "\n".join(format_task(t, today) for t in tasks)
