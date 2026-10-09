# Saha Panel Implementation Plan

> Inline yürütme (kullanıcı seçimi). Her görev: önce test (RED), sonra kod (GREEN), sonra commit. Kod ayrıntısı commit'lerde; bu plan arayüzleri ve test listesini sabitler.

**Goal:** Telegram Mini App paneli, hava kartı görselli sabah özeti, Open-Meteo 429 için MET Norway yedeği.

**Spec:** `docs/superpowers/specs/2026-10-09-saha-panel-design.md`

**Tech:** aiohttp 3.10.10, Pillow 11.0.0, mevcut python-telegram-bot 21.6 / asyncpg / httpx.

## Global Constraints
- Kullanıcıya giden tüm metinler Türkçe; kod içi yorum yok.
- Panel yalnızca `OWNER_ID`'ye açık; imzasız istek asla veri döndürmez.
- Gizli değerler repoya girmez.
- Mevcut 76 test yeşil kalmalı.

## Review Focus
1. Sahte/eski/başka kullanıcıya ait initData → 401/403 (Task 6 testleri).
2. Open-Meteo 429 → MET Norway; ikisi de çökerse özet "Hava alınamadı" ile yine gider (Task 1 + mevcut briefing testi).
3. Geçersiz ayar (25:99 saat, news_count 0) → 400, DB'ye yazılmaz (Task 3/6).
4. Kart çizimi hatası → özet metin olarak gider (Task 4).
5. Panelde program elle düzenlenince boş ders adı → 400 (Task 6).

## Tasks

### Task 1: Hava — saatlik veri, durum, retry, MET Norway yedeği
- Modify `app/weather.py`, `tests/test_weather.py`
- Produces: `DayWeather(..., hourly: tuple[float,...] = (), condition: str = "")`, `parse_openmeteo(data)`, `parse_metno(data, today: date, tz)`, `fetch(lat, lon, tz_name, http)` (fallback'li), `CONDITION_TR: dict[str,str]`
- Tests: openmeteo parse (hourly 24, weather_code → condition), metno parse (yerel güne göre min/max, saatlik, yağış → %), fetch 429→metno (httpx.MockTransport), her ikisi hata → raise.

### Task 2: Hava kartı
- Create `app/card.py`, `tests/test_card.py`, `assets/fonts/*`
- Produces: `render_card(w: DayWeather, hints: list[str], today: date) -> bytes`
- Tests: PNG imzası, 1080×1080, boş `hourly` ve bilinmeyen condition ile çizer.

### Task 3: Ayarlar + DB eklemeleri
- Create `app/settings.py`, `tests/test_settings.py`; Modify `app/db.py`, `tests/test_db.py`
- Produces: `DEFAULTS`, `SettingsError(ValueError)`, `merge(stored: dict|None, base_time: str) -> dict`, `validate(payload) -> dict`; DB: `get_settings() -> dict|None`, `save_settings(dict)`, `search_notes(q: str, limit=100) -> list[dict]`, `delete_note(id) -> bool`, `delete_schedule(kind, day) -> bool`
- Tests: merge varsayılan, validate saat/sayı/bilinmeyen anahtar; DB testleri (Neon test branch).

### Task 4: Ayar duyarlı özet + fotoğraflı gönderim
- Modify `app/briefing.py`, `app/bot.py`, `tests/test_briefing.py`
- Produces: `WeatherInfo(w, advice, hints)`, `Briefing(text, weather: WeatherInfo|None, header)`, `build(today, src, settings) -> Briefing`, bot `send_briefing` (kart + caption, hata → metin), `reschedule_briefing(app, time_str)`
- Tests: kapalı bölüm çıkmaz, `news_count` uygulanır, hava hatası → weather None + uyarı.

### Task 5: Hata kaydı
- Create `app/status.py`, `tests/test_status.py`
- Produces: `ErrorBuffer(logging.Handler)` (`records() -> list[dict]`, maks 20), `install() -> ErrorBuffer`, `STARTED_AT`
- Tests: ERROR yakalanır, INFO yakalanmaz, 20 sınırı.

### Task 6: Web — initData doğrulama + API
- Create `app/webauth.py`, `app/web.py`, `tests/test_webauth.py`, `tests/test_web.py`
- Produces: `verify_init_data(init_data: str, bot_token: str, max_age: int = 86400, now: float|None = None) -> dict` (user dict; hata → `AuthError`), `sign_init_data(user: dict, bot_token: str, auth_date: int) -> str` (test/dev yardımcı), `build_web_app(tg_app) -> aiohttp.web.Application`, `start_web(tg_app, port) -> AppRunner`
- Tests: imza geçerli/yanlış/eski/başka kullanıcı; API 401; ayar GET/PUT (400 geçersiz); program PUT doğrulama; not silme; health.

### Task 7: Arayüz
- Create `app/static/index.html`, `app/static/app.css`, `app/static/app.js`
- Doğrulama: Chrome'da `#tgWebAppData=<imzalı>` ile açıp 4 sekmeyi gez, ekran görüntüsü.

### Task 8: Bot entegrasyonu + deploy
- Modify `app/bot.py` (`/panel`, menü düğmesi), `app/main.py` (aiohttp, status.install), `app/config.py` (`public_url`), `requirements.txt`, `render.yaml`, `README.md`
- Tests: config public_url (PUBLIC_URL > RENDER_EXTERNAL_URL > None); tam suite; push.
