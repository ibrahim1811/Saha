# Saha — Telegram Mini App paneli, fotoğraflı özet, hava yedeği

## Amaç
Kayra botu Telegram içinden açılan bir panelden (Telegram Mini App) görebilsin ve ayarlayabilsin; sabah özeti hava kartı görseliyle gelsin; Render'da Open-Meteo 429 verdiğinde hava yine gelsin.

## 1. Hava yedeği
- Render loglarında doğrulandı: Open-Meteo paylaşılan IP yüzünden `429 Too Many Requests`.
- `weather.fetch`: Open-Meteo'yu dener (429/5xx/ağ hatasında 1 sn sonra 1 kez daha). Yine olmazsa MET Norway `locationforecast/2.0/compact` (anahtarsız, `User-Agent` zorunlu).
- MET Norway yağış ihtimali vermez; bugünün saatlik `precipitation_amount` toplamından tahmin: 0 → %0, < 1 mm → %40, ≥ 1 mm → %70.
- `DayWeather`'a eklenir: `hourly: tuple[float, ...]` (yerel saat 0–23), `condition: str` (`clear`, `partly`, `cloudy`, `fog`, `rain`, `storm`, `snow`).

## 2. Hava kartı görseli
- `app/card.py`: Pillow ile 1080×1080 PNG. İçerik: "Buca · <tarih>", durum ikonu (şekillerle çizilir), büyük sıcaklık (en yüksek), en düşük/en yüksek, yağış %, rüzgâr, 06–23 saatlik sıcaklık çizgi grafiği, kıyafet ipucu rozetleri (ceket, şemsiye…).
- Font repoda: `assets/fonts/NotoSans-{Regular,Bold}.ttf` (OFL, Türkçe karakter destekli).
- Gönderim: kart `send_photo` ile, açıklamasında hava özeti ve kıyafet önerisi (en fazla 1024 karakter); ardından diğer bölümler metin olarak. Kart çizimi hata verirse özet eskisi gibi tamamen metin olarak gider.

## 3. Ayarlar
`settings` tablosu (`key TEXT PRIMARY KEY, value JSONB`), tek satır `key='main'`. Varsayılanlar:
```json
{"briefing_time": "07:00", "sections": {"weather": true, "lessons": true, "finance": true, "news": true}, "photo_card": true, "news_count": 5}
```
Doğrulama: saat `HH:MM`, `news_count` 1–10, bilinmeyen anahtarlar reddedilir. Saat değişince `sabah-ozeti` job'ı hemen yeniden planlanır. `BRIEFING_TIME` env yalnızca ilk varsayılan.

## 4. Mini App
- Bot açılışta sahibinin sohbetine menü düğmesi kurar: `MenuButtonWebApp("Panel", <PUBLIC_URL>/)`. `/panel` komutu da aynı bağlantıyı gönderir. `PUBLIC_URL` yoksa `RENDER_EXTERNAL_URL` kullanılır; ikisi de yoksa düğme kurulmaz (yerel geliştirme).
- Sunucu: `aiohttp`, PTB ile aynı event loop'ta (`post_init`'te başlar), `PORT`'u dinler. Eski thread'li health sunucusu kaldırılır; `/health` aiohttp'de.
- Kimlik doğrulama: her `/api/*` isteği `Authorization: tma <initData>` taşır. Sunucu Telegram'ın HMAC algoritmasıyla doğrular (`secret = HMAC_SHA256("WebAppData", bot_token)`), `auth_date` 24 saatten eski olmamalı, `user.id == OWNER_ID`. Aksi halde 401/403.
- API:
  - `GET /api/status` → bot çalışma süresi, sonraki özet zamanı, son 20 hata, ayarlar
  - `GET /api/settings`, `PUT /api/settings`
  - `GET /api/schedules`, `PUT /api/schedules/okul`, `PUT /api/schedules/dershane/{cumartesi|pazar}`, `DELETE` aynı yollar
  - `GET /api/notes?q=`, `DELETE /api/notes/{id}`
  - `GET /api/reminders`, `POST /api/reminders` (`{"text": "yarın 15'te …"}` doğal dil), `DELETE /api/reminders/{id}`
  - `GET /api/briefing/preview` → `{text, card}` (`card` base64 PNG ya da null)
  - `POST /api/briefing/send`
- Arayüz: tek `index.html` + `app.css` + `app.js` (build yok), `telegram-web-app.js` ile Telegram teması (`--tg-theme-*`), 4 sekme: Durum, Ayarlar, Program, Notlar. Telegram'ın MainButton/BackButton/haptic özellikleri kullanılır.

## 5. Hata kaydı
`app/status.py`: logging handler son 20 ERROR kaydını (zaman, modül, mesaj, istisna son satırı) bellekte tutar; `started_at`.

## Hata yönetimi
API hataları JSON `{"error": "<Türkçe mesaj>"}` ve uygun HTTP kodu; beklenmeyen hata 500 + log. Doğrulama hatası 400.

## Test
- `weather`: Open-Meteo 429 → MET Norway'e düşer; MET Norway ayrıştırma; durum eşleme.
- `card`: geçerli PNG, boş saatlik veriyle de çizer.
- `settings`: varsayılan birleştirme, doğrulama hataları.
- `webauth`: geçerli imza kabul, yanlış hash / eski tarih / başka kullanıcı reddedilir.
- `web`: aiohttp test istemcisiyle yetkisiz 401, ayar okuma/yazma, program PUT doğrulaması, not silme.
- `briefing`: kapalı bölümler çıkmaz, haber sayısı uygulanır.
