from datetime import datetime

from app.schedule import ALL_DAYS

SYSTEM = (
    "Kullanıcının hatırlatma isteğini ayrıştır. Sadece JSON döndür: "
    '{"when": "YYYY-MM-DDTHH:MM", "text": "neyin hatırlatılacağı"}. '
    "'yarın', 'cuma', '2 saat sonra' gibi ifadeleri verilen şu anki zamana göre çöz. "
    "Saat belirtilmemişse 09:00 kullan. text alanına 'hatırlat' kelimesini koyma."
)


class ReminderError(ValueError):
    pass


def parse_result(data, now: datetime) -> tuple[datetime, str]:
    try:
        when = datetime.fromisoformat(data["when"])
        text = str(data["text"]).strip()
    except (KeyError, TypeError, ValueError) as e:
        raise ReminderError("Ne zaman hatırlatacağımı anlayamadım") from e
    if not text:
        raise ReminderError("Neyi hatırlatacağımı anlayamadım")
    when = when.replace(tzinfo=now.tzinfo)
    if when <= now:
        raise ReminderError(f"Bu zaman geçmişte: {format_when(when.astimezone(now.tzinfo))}")
    return when, text


async def parse(message: str, now: datetime, llm) -> tuple[datetime, str]:
    prompt = f"Şu an: {now:%Y-%m-%d %H:%M} ({ALL_DAYS[now.weekday()]}). İstek: {message}"
    return parse_result(await llm.ask_json(prompt, SYSTEM), now)


def format_when(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y %H:%M")
