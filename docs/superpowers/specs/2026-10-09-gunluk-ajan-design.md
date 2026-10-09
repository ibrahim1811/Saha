# Günlük Ajan — Tasarım

## Amaç
Kayra için tek kullanıcılı, Telegram üzerinden çalışan kişisel günlük asistan. Her sabah hava + kıyafet önerisi + günün dersleri + döviz + haber özeti atar; sesli not alır, hatırlatıcı kurar, notlar/program hakkında soru yanıtlar.

## Kapsam (v1)
1. Sabah özeti (07:00 Europe/Istanbul)
2. Ders programı fotoğraftan okuma
3. Sesli not
4. Doğal dille hatırlatıcı
5. AI sohbet (notlar + program bağlamıyla)

Kapsam dışı: çok kullanıcı, takvim entegrasyonu, web arayüzü.

## Teknoloji
- Python 3.12, `python-telegram-bot` v21 (async, JobQueue/APScheduler)
- Postgres (Neon ücretsiz) — `asyncpg`
- Claude API (`claude-sonnet-5-5`): fotoğraf okuma, hatırlatıcı ayrıştırma, kıyafet önerisi, sohbet
- Groq Whisper (`whisper-large-v3`): ses → yazı
- Open-Meteo: hava (anahtar gerektirmez)
- Döviz/altın: Truncgil finans JSON (`finans.truncgil.com/v4/today.json`)
- Haber: RSS (ör. NTV / BBC Türkçe) — `feedparser`
- Deploy: Render Web Service + cron-job.org ile `/health` ping (uyumayı engeller)

## Ortam değişkenleri
`TELEGRAM_TOKEN`, `OWNER_ID`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `DATABASE_URL`, `TZ=Europe/Istanbul`, `LAT=38.39`, `LON=27.17`, `BRIEFING_TIME=07:00`.
Açık adres hiçbir yerde saklanmaz; yalnızca Buca ilçe koordinatı.

## Modüller
| Dosya | Sorumluluk |
|---|---|
| `app/main.py` | Uygulamayı kurar, handler'ları ve job'ları kaydeder, `/health` HTTP endpoint |
| `app/config.py` | Ortam değişkenlerini okur, eksikse başlatmayı durdurur |
| `app/db.py` | Bağlantı havuzu + şema oluşturma + sorgu fonksiyonları |
| `app/auth.py` | `OWNER_ID` dışındaki tüm güncellemeleri reddeden filtre |
| `app/schedule.py` | Foto → Claude vision → JSON program; gün için ders listesi |
| `app/weather.py` | Open-Meteo çağrısı → sade `DayWeather` |
| `app/outfit.py` | `DayWeather` → kural tabanlı ipuçları + Claude ile kısa öneri metni |
| `app/finance.py` | USD, EUR, gram altın |
| `app/news.py` | RSS'ten 5 başlık |
| `app/briefing.py` | Bölümleri toplar, her bölüm bağımsız hata yakalar, tek mesaj üretir |
| `app/notes.py` | Ses dosyasını indir, Groq'a gönder, notu kaydet |
| `app/reminders.py` | Metin → Claude → `{when, text}`; kaydet ve job planla; açılışta yeniden yükle |
| `app/chat.py` | Son notlar + program bağlamıyla Claude'a soru |
| `app/llm.py` | Anthropic istemcisi sarmalayıcı (tek yerde model adı, timeout) |

## Veri modeli
```sql
schedules(id, kind TEXT CHECK (kind IN ('okul','dershane')), day TEXT NULL, data JSONB, created_at)
-- okul: day NULL, data = {"pazartesi":[{"saat":"08:30","ders":"Mat"}...], ...}
-- dershane: day IN ('cumartesi','pazar'), data = [{"saat":..,"ders":..}]
notes(id, text, source TEXT, created_at)
reminders(id, text, due_at TIMESTAMPTZ, sent BOOL DEFAULT false, created_at)
```
Aynı `kind`+`day` için yeni kayıt eskisini değiştirir (upsert).

## Akışlar

### Ders programı
1. Kullanıcı foto atar → bot inline butonla sorar: Okul (hafta içi) / Dershane Cumartesi / Dershane Pazar.
2. Foto + talimat Claude'a; çıktı JSON şemasına göre doğrulanır.
3. Bot okunan programı metin olarak gösterir: ✅ Kaydet / 🔁 Tekrar dene.
4. Onayda upsert.

### Sabah özeti (07:00 + `/ozet`)
Sıra: selam + tarih → hava + kıyafet → bugünün dersleri → döviz/altın → haberler.
Her bölüm `try/except` ile ayrı; hata olursa o bölüm `⚠️ <bölüm> alınamadı` yazar ve hata loglanır.
Kıyafet: kural tabanlı ipuçları (min < 15° → ceket, yağış ≥ %40 → şemsiye, gün içi fark ≥ 8° → katmanlı, rüzgâr ≥ 30 km/s → rüzgârlık) Claude'a girdi olarak verilir; Claude 2-3 cümlelik doğal metin yazar. Claude hata verirse ipuçları madde olarak doğrudan gönderilir.

### Sesli not
Ses → geçici dosya → Groq → `notes` kaydı → "📝 Kaydedildi: …". Hata: kullanıcıya bildirim, dosya silinmez, log.

### Hatırlatıcı
`/hatirlat <metin>` veya "hatırlat" içeren metin → Claude şu anki zamanı da alarak `{"when": ISO8601, "text": ...}` döner → geçmiş tarihse reddet → kaydet + `job_queue.run_once`. Açılışta `sent=false` olanlar yüklenir; vadesi geçmişse "(gecikmeli)" ile hemen gönderilir.

### AI sohbet
Diğer kalıplara uymayan metin → son 50 not + kayıtlı program + bugünün tarihi sistem bağlamı olarak Claude'a.

## Komutlar
`/start`, `/ozet`, `/program`, `/notlar`, `/hatirlat <metin>`, `/hatirlaticilar`, `/sil <id>`.

## Hata yönetimi ilkeleri
- Hiçbir hata sessizce yutulmaz: ya kullanıcıya iletilir ya loglanır (çoğunlukla ikisi).
- Dış çağrılarda timeout (10 sn; Claude 30 sn).
- Global error handler: beklenmeyen hata → log + sahibine kısa mesaj.

## Test
`pytest` + `pytest-asyncio`:
- `outfit` kural fonksiyonu (sınır değerler)
- `schedule` JSON doğrulama + gün seçimi (hafta içi okul, hafta sonu dershane)
- `reminders` Claude çıktısı ayrıştırma (LLM mock'lanır)
- `briefing` bölüm hatasında diğerlerinin yine gelmesi
Dış API'ler test edilmez, mock'lanır.
