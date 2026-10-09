import logging

from app.weather import DayWeather, summary

log = logging.getLogger(__name__)

SYSTEM = (
    "Sen Kayra'nın kişisel asistanısın. Buca/İzmir için bugünkü havaya göre ne giymesi gerektiğini "
    "Türkçe, samimi ve en fazla 3 cümleyle söyle. Ceket, şemsiye gibi somut öneriler ver."
)


def hints(w: DayWeather) -> list[str]:
    out = []
    if w.t_min < 15:
        out.append("ceket al")
    if w.rain_prob >= 40:
        out.append("şemsiye al")
    if w.t_max - w.t_min >= 8:
        out.append("katmanlı giyin")
    if w.wind_max >= 30:
        out.append("rüzgârlık iyi olur")
    if w.t_max >= 28:
        out.append("ince ve açık renkli giyin")
    return out


async def advice(w: DayWeather, llm) -> str:
    h = hints(w)
    prompt = f"Bugünün havası: {summary(w)}. Kural ipuçları: {', '.join(h) or 'yok'}. Ne giymeliyim?"
    try:
        return (await llm.ask(prompt, SYSTEM, max_tokens=200)).strip()
    except Exception:
        log.exception("Kıyafet önerisi LLM'den alınamadı")
        return "\n".join(f"• {x}" for x in h) if h else "Hava ılıman, rahat giyinebilirsin."
