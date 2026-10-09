# Saha

Saha (@Saha_habercisi_bot) — Kayra'nın kişisel Telegram asistanı: sabah özeti (hava + kıyafet önerisi, dersler, piyasa, haberler), ders programı, sesli not, hatırlatıcı, AI sohbet.

## Gereken anahtarlar
| Değişken | Nereden |
|---|---|
| `TELEGRAM_TOKEN` | Telegram → @BotFather → `/newbot` |
| `OWNER_ID` | Telegram → @userinfobot (kendi sayısal ID'n) |
| `GROQ_API_KEY` | console.groq.com → API Keys (LLM + ses için tek anahtar) |
| `DATABASE_URL` | neon.tech → ücretsiz proje → Connection string |

Anahtarsız kullanılan servisler: Open-Meteo (hava), Truncgil (döviz/altın), BBC Türkçe RSS (haber).

xAI Grok kullanmak istersen: `LLM_API_KEY=<xai anahtarı>`, `LLM_BASE_URL=https://api.x.ai/v1`, `LLM_MODEL` ve `LLM_VISION_MODEL` için Grok model adları. Sesli not yine `GROQ_API_KEY` ister.

## Yerelde çalıştırma
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env   # doldur
set -a; source .env; set +a
.venv/Scripts/python -m app.main
```

## Test
```bash
.venv/Scripts/python -m pytest -q
```
DB testleri için `TEST_DATABASE_URL` ayarla (ayrı bir Neon branch'i önerilir).

## Render
1. Repoyu GitHub'a it → Render → New → Blueprint → bu repo (`render.yaml` okunur).
2. Gizli değişkenleri Render panelinden gir.
3. cron-job.org → her 10 dakikada `https://<servis>.onrender.com/health` GET (ücretsiz plan uyumasın diye).
4. Yerel botu kapat: aynı token iki yerde polling yaparsa çakışır.
