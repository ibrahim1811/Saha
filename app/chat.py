from datetime import datetime

from app.schedule import ALL_DAYS, format_all

SYSTEM = (
    "Sen Kayra'nın kişisel asistanısın. Türkçe, kısa ve samimi cevap ver. "
    "Aşağıda Kayra'nın notları ve ders programı var; soruyla ilgiliyse bunları kullan. "
    "Bilmediğin bir şeyi uydurma, notlarda yoksa yok de."
)


def build_context(notes: list[dict], schedules: dict, now: datetime) -> str:
    note_lines = [f"[{n['created_at'].astimezone(now.tzinfo):%d.%m.%Y %H:%M}] {n['text']}" for n in notes]
    return "\n\n".join([
        SYSTEM,
        f"Şu an: {now:%d.%m.%Y %H:%M} ({ALL_DAYS[now.weekday()]})",
        "Notlar:\n" + ("\n".join(note_lines) if note_lines else "Henüz not yok."),
        "Ders programı:\n" + format_all(schedules),
    ])


async def answer(question: str, db, llm, now: datetime) -> str:
    context = build_context(await db.recent_notes(50), await db.all_schedules(), now)
    return (await llm.ask(question, context, max_tokens=1024)).strip()
