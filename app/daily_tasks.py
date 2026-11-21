import hashlib
import random
from datetime import date


TASK_POOL = [
    {"theme": "İletişim", "task": "{name}'e bugün en az 3 kez \"seninle konuşmak iyi geliyor\" diye hissettir."},
    {"theme": "Şefkat", "task": "{name}'in bugün işini kolaylaştıracak küçük bir yardım yap."},
    {"theme": "Sabır", "task": "Bugün {name}'e kızmadan, 2 dakika dinleyerek cevap ver."},
    {"theme": "Sevgi", "task": "Gün içinde {name}'e 25 kez \"seni seviyorum\" yaz."},
    {"theme": "Boykot", "task": "Bugün hiçbir gerekçeyle boykot veya trip başlatma."},
    {"theme": "Sabah", "task": "Güne {name}'e kısa ve sıcak bir iyi sabahlar mesajıyla başla."},
    {"theme": "Gülümseme", "task": "Bugün {name}'e 3 farklı komik veya içten şey gönder."},
    {"theme": "Minnettarlık", "task": "{name}'in yaptığı 3 şeyi bugün açıkça teşekkür ederek belirt."},
    {"theme": "Özel mesaj", "task": "Bugün {name}'e 300 karakterden kısa, geçmişteki güzel bir anıyı hatırlatan not yaz."},
    {"theme": "Günlük ritim", "task": "Bugün {name}'in rahatlaması için günü güzelleştiren bir mini sürpriz yap."},
    {"theme": "Destek", "task": "{name}'in karşılaşabileceği bir dert için bugün tek yapıcı çözüm öner."},
    {"theme": "Dürüstlük", "task": "Bugün {name}'e yaşadığın bir duyguyu saklamadan nazikçe anlat."},
    {"theme": "Küçük hediye", "task": "Bugün {name}'e bir emoji, meme, fotoğraf veya küçük sürpriz seç."},
    {"theme": "Affetme", "task": "Bir mesele çıkarsa 10 dakika içinde nazikçe konuşup çözüme odaklan."},
    {"theme": "Birlik", "task": "Bugün {name}'le aynı anda yapabileceğin küçük bir etkinlik planla."},
    {"theme": "Odak", "task": "Telefonu bir kenara koyup {name}'le en az 10 dakika tam dikkat et."},
    {"theme": "Güven", "task": "{name}'e bugün verebileceğin küçük bir söz ver ve günü sonunda yerine getir."},
    {"theme": "İlham", "task": "Bugün {name}'e moral verecek kısa bir söz veya motivasyon gönder."},
    {"theme": "Merak", "task": "{name}'e bugünü nasıl geçirdiğini iyi dinleyerek sor."},
    {"theme": "Özür", "task": "Bir hata yaparsan \"ben suçluyum, seni üzdüm\" diyerek özür dile."},
]


PENALTIES = [
    "Akşam birlikte 10 dakikalık samimi bir sohbet yap.",
    "Karşı tarafa özür dolu 100 kelimelik bir not gönder.",
    "Karşı tarafın seçtiği, zararsız bir tatlı veya içecek müzikli paylaşılır.",
]


def _seed(today: date, role: str) -> int:
    raw = f"{today.isoformat()}:{role}".encode()
    return int(hashlib.sha256(raw).hexdigest()[:16], 16)


def select_task(today: date, role: str, name: str) -> dict:
    rng = random.Random(_seed(today, role))
    item = rng.choice(TASK_POOL)
    text = item["task"].replace("{name}", name)
    return {"theme": item["theme"], "text": text, "status": "pending", "outcome": None}


def ensure_day(state: dict | None, today: date, owner_name: str, partner_name: str) -> dict:
    state = state or {}
    day = today.isoformat()
    data = state.setdefault("days", {})
    day_data = data.setdefault(day, {})
    day_data.setdefault("owner", select_task(today, "owner", partner_name))
    day_data.setdefault("partner", select_task(today, "partner", owner_name))
    state["current"] = day
    return state


async def select_ai(llm, today: date, role: str, name: str) -> dict | None:
    prompt = (
        f"{today.isoformat()} için bugün {name} kişisine verilebilecek kısa, güvenli, "
        "romantik ama özgün bir günlük görev seç. Aynı konuya bağlı kalma. "
        "Sevgi, iletişim, destek, sabır, sürpriz, güven, özür veya mizah tema olsun. "
        "JSON: {\"theme\":\"tema\",\"text\":\"görev metni\"}"
    )
    try:
        result = await llm.ask_json(prompt, "Romantik ilişki günlük görevleri üret. Kişisel veya zararlı istekler verme.", max_tokens=220)
        theme = str(result.get("theme", "")).strip()[:40]
        text = str(result.get("text", "")).strip()[:220]
        if theme and text:
            return {"theme": theme, "text": text, "status": "pending", "outcome": None}
    except Exception:
        pass
    return None
