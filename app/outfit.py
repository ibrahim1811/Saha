import logging

from app.weather import DayWeather, summary

log = logging.getLogger(__name__)

SYSTEM = (
    "Sen Saha'sın, Kayra'nın kişisel asistanı. Buca/İzmir için verilen havaya göre ne giymesi gerektiğini "
    "Türkçe, samimi ve en fazla 2 kısa cümleyle söyle. Sadece verilen sayılara dayan: yağış ihtimali %40'ın altındaysa "
    "şemsiye önerme, sıcaklığın gün içinde nasıl değiştiğini doğru anlat (sabah serin, öğlen sıcak gibi). "
    "Kural ipuçlarını mutlaka dikkate al, marka ya da gereksiz aksesuar sayma."
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
    timeline = []
    if w.t_morning is not None:
        timeline.append(f"sabah 08:00'de {w.t_morning:.0f}°")
    timeline.append(f"gün içinde en yüksek {w.t_max:.0f}°")
    if w.t_evening is not None:
        timeline.append(f"akşam 19:00'da {w.t_evening:.0f}°")
    prompt = (
        f"Hava: {', '.join(timeline)}, en düşük {w.t_min:.0f}°, yağış ihtimali %{w.rain_prob}, rüzgâr {w.wind_max:.0f} km/s. "
        f"Kural ipuçları: {', '.join(h) or 'yok'}. Ne giymeliyim?"
    )
    try:
        return (await llm.ask(prompt, SYSTEM, max_tokens=600)).strip()
    except Exception:
        log.exception("Kıyafet önerisi LLM'den alınamadı")
        return "\n".join(f"• {x}" for x in h) if h else "Hava ılıman, rahat giyinebilirsin."
