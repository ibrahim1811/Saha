# Günlük Ajan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kayra'ya her sabah 07:00'de hava + kıyafet önerisi + günün dersleri + piyasa + haber özeti atan; sesli not, hatırlatıcı ve AI sohbet sunan tek kullanıcılı Telegram botu.

**Architecture:** `python-telegram-bot` v21 (polling + JobQueue) tek süreçte çalışır; iş mantığı Telegram'dan bağımsız küçük modüllerde (`weather`, `outfit`, `schedule`, `reminders`, …) durur ve birim test edilir. Kalıcı veri Postgres'te; Claude fotoğraf okuma / ayrıştırma / sohbet için, Groq Whisper ses için. Render Web Service'te `/health` endpoint'i ile çalışır.

**Tech Stack:** Python 3.12, python-telegram-bot[job-queue] 21, anthropic, groq, asyncpg, httpx, feedparser, tzdata, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-10-09-gunluk-ajan-design.md`

## Global Constraints

- Saat dilimi her yerde `Europe/Istanbul`; naive datetime bu dilimde kabul edilir.
- Konum yalnızca Buca ilçe koordinatı: `LAT=38.39`, `LON=27.17`. Açık adres kodda, DB'de, logda yer almaz.
- Sabah özeti saati `BRIEFING_TIME=07:00`.
- Claude modeli tek yerde: `app/llm.py` → `MODEL = "claude-sonnet-5-5"`.
- Groq modeli: `whisper-large-v3`, `language="tr"`.
- Dış HTTP çağrılarında timeout 10 sn; Claude ve Groq 30 sn.
- Hiçbir hata sessizce yutulmaz: `log.exception(...)` ve/veya kullanıcıya mesaj.
- Bot yalnızca `OWNER_ID`'ye cevap verir.
- Kullanıcıya giden tüm metinler Türkçe.
- Kod içi yorum yazılmaz (proje kuralı).
- Not: Spec'te okul programı için `day NULL` yazıyordu; upsert kolaylığı için `day = ''` kullanılır (davranış aynı).

## Review Focus

1. Claude JSON'u ```json bloğu içinde ya da açıklama cümlesiyle döndürür → yine ayrıştırılmalı (Task 2 testleri).
2. Hatırlatıcı zamanı saat dilimsiz ya da geçmişte gelir → İstanbul saati kabul edilmeli, geçmiş reddedilmeli (Task 7 testleri).
3. O gün için program fotoğrafı hiç yüklenmemiş (ör. Cumartesi dershane) → çökme değil "kayıtlı program yok" mesajı (Task 6 testleri).
4. Sahibi olmayan biri bota yazar → hiçbir handler çalışmamalı (Task 10 `gate` testi).
5. Claude cevabı / not listesi 4096 karakteri aşar → Telegram'a parçalara bölünerek gitmeli (Task 8 `split_message` testi).

---

## Dosya Yapısı

```
gunluk-ajan/
  app/
    __init__.py
    config.py      ortam değişkenleri → Config
    llm.py         Claude sarmalayıcı + extract_json
    db.py          asyncpg havuzu, şema, sorgular
    weather.py     Open-Meteo → DayWeather
    outfit.py      kural ipuçları + Claude kıyafet önerisi
    finance.py     döviz / altın
    news.py        RSS başlıkları
    schedule.py    program foto okuma, doğrulama, gün seçimi, biçimlendirme
    reminders.py   doğal dil → (zaman, metin)
    notes.py       Groq ile ses → yazı
    chat.py        bağlamlı soru-cevap
    textutil.py    split_message
    briefing.py    sabah özeti birleştirici
    bot.py         Telegram handler'ları, gate, job'lar
    main.py        giriş noktası + /health
  tests/
    __init__.py
    fakes.py
    test_*.py
  requirements.txt
  pytest.ini
  render.yaml
  .env.example
  .gitignore
  README.md
```

---

### Task 1: İskelet + config

**Files:**
- Create: `requirements.txt`, `pytest.ini`, `.gitignore`, `.env.example`, `app/__init__.py`, `app/config.py`, `tests/__init__.py`, `tests/fakes.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `app.config.Config` (frozen dataclass: `telegram_token: str, owner_id: int, anthropic_key: str, groq_key: str, database_url: str, tz: ZoneInfo, lat: float, lon: float, briefing_time: datetime.time (tz'li), port: int`), `app.config.load(env: Mapping[str,str] = os.environ) -> Config`
- Produces: `tests.fakes.FakeLLM`, `tests.fakes.FakeDB`

- [ ] **Step 1: Proje dosyalarını oluştur**

`requirements.txt`:
```
python-telegram-bot[job-queue]==21.6
anthropic>=0.40
groq>=0.11
asyncpg==0.29.0
httpx>=0.27
feedparser==6.0.11
tzdata
pytest==8.3.3
pytest-asyncio==0.24.0
```

`pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
pythonpath = .
testpaths = tests
```

`.gitignore`:
```
.venv/
__pycache__/
.env
*.pyc
```

`.env.example`:
```
TELEGRAM_TOKEN=
OWNER_ID=
ANTHROPIC_API_KEY=
GROQ_API_KEY=
DATABASE_URL=postgresql://user:pass@host/db
TZ=Europe/Istanbul
LAT=38.39
LON=27.17
BRIEFING_TIME=07:00
```

`app/__init__.py` ve `tests/__init__.py`: boş.

`tests/fakes.py`:
```python
from app.llm import extract_json


class FakeLLM:
    def __init__(self, reply="", exc=None):
        self.reply = reply
        self.exc = exc
        self.calls = []

    async def ask(self, prompt, system="", image=None, max_tokens=1024):
        self.calls.append({"prompt": prompt, "system": system, "image": image})
        if self.exc:
            raise self.exc
        return self.reply

    async def ask_json(self, prompt, system="", image=None):
        return extract_json(await self.ask(prompt, system, image))


class FakeDB:
    def __init__(self, schedules=None, notes=None):
        self.schedules = schedules or {}
        self.notes = notes or []

    async def get_schedule(self, kind, day=""):
        return self.schedules.get((kind, day))

    async def all_schedules(self):
        return {
            "okul": self.schedules.get(("okul", "")),
            "cumartesi": self.schedules.get(("dershane", "cumartesi")),
            "pazar": self.schedules.get(("dershane", "pazar")),
        }

    async def recent_notes(self, limit=50):
        return self.notes[:limit]
```

- [ ] **Step 2: Sanal ortam ve bağımlılıklar**

Run:
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```
Expected: hatasız kurulum.

- [ ] **Step 3: Failing test yaz** — `tests/test_config.py`
```python
from datetime import time

import pytest

from app.config import load

BASE = {
    "TELEGRAM_TOKEN": "t",
    "OWNER_ID": "42",
    "ANTHROPIC_API_KEY": "a",
    "GROQ_API_KEY": "g",
    "DATABASE_URL": "postgresql://x",
}


def test_load_defaults():
    cfg = load(BASE)
    assert cfg.owner_id == 42
    assert cfg.tz.key == "Europe/Istanbul"
    assert (cfg.lat, cfg.lon) == (38.39, 27.17)
    assert cfg.briefing_time.replace(tzinfo=None) == time(7, 0)
    assert cfg.briefing_time.tzinfo is cfg.tz
    assert cfg.port == 10000


def test_load_overrides():
    cfg = load({**BASE, "BRIEFING_TIME": "06:45", "PORT": "8080"})
    assert cfg.briefing_time.replace(tzinfo=None) == time(6, 45)
    assert cfg.port == 8080


def test_missing_vars_listed():
    with pytest.raises(RuntimeError) as e:
        load({"TELEGRAM_TOKEN": "t"})
    assert "OWNER_ID" in str(e.value) and "GROQ_API_KEY" in str(e.value)
```

- [ ] **Step 4: Testin düştüğünü gör**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config'` (ve `app.llm` yok uyarısı; `fakes` henüz import edilmiyor).

- [ ] **Step 5: `app/config.py`**
```python
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

REQUIRED = ["TELEGRAM_TOKEN", "OWNER_ID", "ANTHROPIC_API_KEY", "GROQ_API_KEY", "DATABASE_URL"]


@dataclass(frozen=True)
class Config:
    telegram_token: str
    owner_id: int
    anthropic_key: str
    groq_key: str
    database_url: str
    tz: ZoneInfo
    lat: float
    lon: float
    briefing_time: time
    port: int


def load(env: Mapping[str, str] = os.environ) -> Config:
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        raise RuntimeError(f"Eksik ortam değişkenleri: {', '.join(missing)}")
    tz = ZoneInfo(env.get("TZ", "Europe/Istanbul"))
    hour, minute = env.get("BRIEFING_TIME", "07:00").split(":")
    return Config(
        telegram_token=env["TELEGRAM_TOKEN"],
        owner_id=int(env["OWNER_ID"]),
        anthropic_key=env["ANTHROPIC_API_KEY"],
        groq_key=env["GROQ_API_KEY"],
        database_url=env["DATABASE_URL"],
        tz=tz,
        lat=float(env.get("LAT", "38.39")),
        lon=float(env.get("LON", "27.17")),
        briefing_time=time(int(hour), int(minute), tzinfo=tz),
        port=int(env.get("PORT", "10000")),
    )
```

- [ ] **Step 6: Testler geçsin**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**
```bash
git add -A
git commit -m "feat: proje iskeleti ve config"
```

---

### Task 2: Claude sarmalayıcı (`llm.py`)

**Files:**
- Create: `app/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Produces: `MODEL: str`, `class LLMError(Exception)`, `extract_json(text: str) -> dict | list`, `class LLM(api_key: str, client=None)` with `async ask(prompt: str, system: str = "", image: bytes | None = None, max_tokens: int = 1024) -> str` and `async ask_json(prompt: str, system: str = "", image: bytes | None = None) -> dict | list`

- [ ] **Step 1: Failing test** — `tests/test_llm.py`
```python
from types import SimpleNamespace

import pytest

from app.llm import LLM, LLMError, extract_json


def test_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json():
    assert extract_json('İşte:\n```json\n{"a": [1, 2]}\n```\nBu kadar.') == {"a": [1, 2]}


def test_json_with_prose():
    assert extract_json('Tabii! [{"ders": "Mat"}] umarım işine yarar') == [{"ders": "Mat"}]


def test_no_json_raises():
    with pytest.raises(LLMError):
        extract_json("Programı okuyamadım.")


def test_broken_json_raises():
    with pytest.raises(LLMError):
        extract_json('{"a": }')


class _Messages:
    def __init__(self):
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"ok": true}')])


async def test_ask_sends_image_and_system():
    messages = _Messages()
    llm = LLM("k", client=SimpleNamespace(messages=messages))
    out = await llm.ask_json("oku", system="sys", image=b"\xff\xd8")
    assert out == {"ok": True}
    content = messages.kwargs["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[1] == {"type": "text", "text": "oku"}
    assert messages.kwargs["system"] == "sys"
```

- [ ] **Step 2: Düştüğünü gör**

Run: `.venv/Scripts/python -m pytest tests/test_llm.py -v`
Expected: FAIL — `No module named 'app.llm'`.

- [ ] **Step 3: `app/llm.py`**
```python
import base64
import json
import re

from anthropic import AsyncAnthropic

MODEL = "claude-sonnet-5-5"


class LLMError(Exception):
    pass


def extract_json(text: str):
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise LLMError(f"JSON bulunamadı: {text[:200]}")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"Geçersiz JSON: {e}") from e


class LLM:
    def __init__(self, api_key: str, client=None):
        self.client = client or AsyncAnthropic(api_key=api_key, timeout=30)

    async def ask(self, prompt: str, system: str = "", image: bytes | None = None, max_tokens: int = 1024) -> str:
        content = []
        if image is not None:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(image).decode()},
            })
        content.append({"type": "text", "text": prompt})
        kwargs = {"model": MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}
        if system:
            kwargs["system"] = system
        resp = await self.client.messages.create(**kwargs)
        return "".join(b.text for b in resp.content if b.type == "text")

    async def ask_json(self, prompt: str, system: str = "", image: bytes | None = None):
        return extract_json(await self.ask(prompt, system, image))
```

- [ ] **Step 4: Testler geçsin**

Run: `.venv/Scripts/python -m pytest tests/test_llm.py tests/test_config.py -v`
Expected: tümü passed.

- [ ] **Step 5: Commit**
```bash
git add -A
git commit -m "feat: Claude sarmalayıcı ve JSON ayrıştırma"
```

---

### Task 3: Veritabanı (`db.py`)

**Files:**
- Create: `app/db.py`
- Test: `tests/test_db.py` (yalnızca `TEST_DATABASE_URL` varsa çalışır)

**Interfaces:**
- Produces: `class DB` with
  - `@classmethod async connect(url: str) -> DB`
  - `async close() -> None`
  - `async save_schedule(kind: str, day: str, data: dict | list) -> None`
  - `async get_schedule(kind: str, day: str = "") -> dict | list | None`
  - `async all_schedules() -> dict` → `{"okul": dict|None, "cumartesi": list|None, "pazar": list|None}`
  - `async add_note(text: str, source: str) -> int`
  - `async recent_notes(limit: int = 50) -> list[dict]` (anahtarlar: `id, text, created_at`; yeniden eskiye)
  - `async add_reminder(text: str, due_at: datetime) -> int`
  - `async pending_reminders() -> list[dict]` (anahtarlar: `id, text, due_at`; artan `due_at`)
  - `async mark_sent(reminder_id: int) -> None`
  - `async delete_reminder(reminder_id: int) -> bool`

- [ ] **Step 1: Test** — `tests/test_db.py`
```python
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.db import DB

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL yok")


@pytest.fixture
async def db():
    d = await DB.connect(URL)
    await d.pool.execute("TRUNCATE schedules, notes, reminders RESTART IDENTITY")
    yield d
    await d.close()


async def test_schedule_upsert(db):
    await db.save_schedule("okul", "", {"pazartesi": [{"saat": "", "ders": "Mat"}]})
    await db.save_schedule("okul", "", {"pazartesi": [{"saat": "", "ders": "Fizik"}]})
    assert (await db.get_schedule("okul"))["pazartesi"][0]["ders"] == "Fizik"
    assert (await db.all_schedules())["cumartesi"] is None


async def test_notes_order(db):
    await db.add_note("ilk", "ses")
    await db.add_note("ikinci", "ses")
    assert [n["text"] for n in await db.recent_notes()] == ["ikinci", "ilk"]


async def test_reminders(db):
    due = datetime.now(timezone.utc) + timedelta(hours=1)
    rid = await db.add_reminder("fatura", due)
    assert [r["id"] for r in await db.pending_reminders()] == [rid]
    await db.mark_sent(rid)
    assert await db.pending_reminders() == []
    assert await db.delete_reminder(rid) is True
    assert await db.delete_reminder(rid) is False
```

- [ ] **Step 2: Düştüğünü gör**

Run: `.venv/Scripts/python -m pytest tests/test_db.py -v`
Expected: `TEST_DATABASE_URL` yoksa ImportError ile FAIL (modül yok). Neon'da ayrı bir test DB'si açıldıysa `TEST_DATABASE_URL` set edilip tekrar çalıştırılır.

- [ ] **Step 3: `app/db.py`**
```python
import json
from datetime import datetime

import asyncpg

SCHEMA = """
CREATE TABLE IF NOT EXISTS schedules (
    id SERIAL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('okul', 'dershane')),
    day TEXT NOT NULL DEFAULT '',
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (kind, day)
);
CREATE TABLE IF NOT EXISTS notes (
    id SERIAL PRIMARY KEY,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS reminders (
    id SERIAL PRIMARY KEY,
    text TEXT NOT NULL,
    due_at TIMESTAMPTZ NOT NULL,
    sent BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class DB:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def connect(cls, url: str) -> "DB":
        pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
        await pool.execute(SCHEMA)
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    async def save_schedule(self, kind: str, day: str, data) -> None:
        await self.pool.execute(
            "INSERT INTO schedules (kind, day, data) VALUES ($1, $2, $3::jsonb) "
            "ON CONFLICT (kind, day) DO UPDATE SET data = EXCLUDED.data, created_at = now()",
            kind, day, json.dumps(data, ensure_ascii=False),
        )

    async def get_schedule(self, kind: str, day: str = ""):
        raw = await self.pool.fetchval("SELECT data FROM schedules WHERE kind = $1 AND day = $2", kind, day)
        return json.loads(raw) if raw is not None else None

    async def all_schedules(self) -> dict:
        return {
            "okul": await self.get_schedule("okul"),
            "cumartesi": await self.get_schedule("dershane", "cumartesi"),
            "pazar": await self.get_schedule("dershane", "pazar"),
        }

    async def add_note(self, text: str, source: str) -> int:
        return await self.pool.fetchval("INSERT INTO notes (text, source) VALUES ($1, $2) RETURNING id", text, source)

    async def recent_notes(self, limit: int = 50) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT id, text, created_at FROM notes ORDER BY created_at DESC, id DESC LIMIT $1", limit
        )
        return [dict(r) for r in rows]

    async def add_reminder(self, text: str, due_at: datetime) -> int:
        return await self.pool.fetchval(
            "INSERT INTO reminders (text, due_at) VALUES ($1, $2) RETURNING id", text, due_at
        )

    async def pending_reminders(self) -> list[dict]:
        rows = await self.pool.fetch("SELECT id, text, due_at FROM reminders WHERE NOT sent ORDER BY due_at")
        return [dict(r) for r in rows]

    async def mark_sent(self, reminder_id: int) -> None:
        await self.pool.execute("UPDATE reminders SET sent = true WHERE id = $1", reminder_id)

    async def delete_reminder(self, reminder_id: int) -> bool:
        result = await self.pool.execute("DELETE FROM reminders WHERE id = $1", reminder_id)
        return result.endswith(" 1")
```

- [ ] **Step 4: Testler**

Run: `.venv/Scripts/python -m pytest tests/test_db.py -v`
Expected: `TEST_DATABASE_URL` yoksa 3 skipped; varsa 3 passed. Tümünü çalıştır: `.venv/Scripts/python -m pytest -v` → hatasız.

- [ ] **Step 5: Commit**
```bash
git add -A
git commit -m "feat: Postgres katmanı"
```

---

### Task 4: Hava + kıyafet önerisi

**Files:**
- Create: `app/weather.py`, `app/outfit.py`
- Test: `tests/test_weather.py`, `tests/test_outfit.py`

**Interfaces:**
- Consumes: `LLM.ask` (Task 2)
- Produces: `weather.DayWeather(t_min: float, t_max: float, t_morning: float, t_evening: float, rain_prob: int, wind_max: float)`, `weather.parse(data: dict) -> DayWeather`, `async weather.fetch(lat: float, lon: float, tz_name: str, http: httpx.AsyncClient) -> DayWeather`, `weather.summary(w: DayWeather) -> str`
- Produces: `outfit.hints(w: DayWeather) -> list[str]`, `async outfit.advice(w: DayWeather, llm) -> str`

- [ ] **Step 1: Failing testler**

`tests/test_weather.py`:
```python
from app.weather import DayWeather, parse, summary


def _data():
    temps = [10.0 + i * 0.5 for i in range(24)]
    return {
        "hourly": {"temperature_2m": temps},
        "daily": {
            "temperature_2m_min": [9.4],
            "temperature_2m_max": [21.6],
            "precipitation_probability_max": [55],
            "wind_speed_10m_max": [18.2],
        },
    }


def test_parse_picks_morning_and_evening():
    w = parse(_data())
    assert w == DayWeather(t_min=9.4, t_max=21.6, t_morning=14.0, t_evening=19.5, rain_prob=55, wind_max=18.2)


def test_parse_null_rain_is_zero():
    d = _data()
    d["daily"]["precipitation_probability_max"] = [None]
    assert parse(d).rain_prob == 0


def test_summary():
    w = DayWeather(9.4, 21.6, 14.0, 19.5, 55, 18.2)
    assert summary(w) == "Sabah 14° → akşam 20° (en düşük 9°, en yüksek 22°), yağış %55, rüzgâr 18 km/s"
```

`tests/test_outfit.py`:
```python
from app.outfit import advice, hints
from app.weather import DayWeather
from tests.fakes import FakeLLM


def w(**kw):
    base = dict(t_min=18, t_max=24, t_morning=19, t_evening=22, rain_prob=0, wind_max=10)
    base.update(kw)
    return DayWeather(**base)


def test_mild_day_no_hints():
    assert hints(w()) == []


def test_jacket_boundary():
    assert "ceket al" in hints(w(t_min=14.9))
    assert "ceket al" not in hints(w(t_min=15))


def test_umbrella_boundary():
    assert "şemsiye al" in hints(w(rain_prob=40))
    assert "şemsiye al" not in hints(w(rain_prob=39))


def test_layers_boundary():
    assert "katmanlı giyin" in hints(w(t_min=16, t_max=24))
    assert "katmanlı giyin" not in hints(w(t_min=17, t_max=24))


def test_wind_and_heat():
    h = hints(w(wind_max=30, t_max=28, t_min=21))
    assert "rüzgârlık iyi olur" in h and "ince ve açık renkli giyin" in h


async def test_advice_uses_llm_and_passes_hints():
    llm = FakeLLM(reply="  İnce ceket al.  ")
    assert await advice(w(t_min=10), llm) == "İnce ceket al."
    assert "ceket al" in llm.calls[0]["prompt"]


async def test_advice_falls_back_on_llm_error():
    llm = FakeLLM(exc=RuntimeError("down"))
    assert await advice(w(t_min=10, rain_prob=70), llm) == "• ceket al\n• şemsiye al\n• katmanlı giyin"


async def test_advice_fallback_mild():
    assert await advice(w(), FakeLLM(exc=RuntimeError())) == "Hava ılıman, rahat giyinebilirsin."
```

- [ ] **Step 2: Düştüğünü gör**

Run: `.venv/Scripts/python -m pytest tests/test_weather.py tests/test_outfit.py -v`
Expected: FAIL — modüller yok.

- [ ] **Step 3: `app/weather.py`**
```python
from dataclasses import dataclass

import httpx

URL = "https://api.open-meteo.com/v1/forecast"


@dataclass(frozen=True)
class DayWeather:
    t_min: float
    t_max: float
    t_morning: float
    t_evening: float
    rain_prob: int
    wind_max: float


def parse(data: dict) -> DayWeather:
    daily = data["daily"]
    hourly = data["hourly"]["temperature_2m"]
    return DayWeather(
        t_min=daily["temperature_2m_min"][0],
        t_max=daily["temperature_2m_max"][0],
        t_morning=hourly[8],
        t_evening=hourly[19],
        rain_prob=int(daily["precipitation_probability_max"][0] or 0),
        wind_max=daily["wind_speed_10m_max"][0],
    )


async def fetch(lat: float, lon: float, tz_name: str, http: httpx.AsyncClient) -> DayWeather:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max,wind_speed_10m_max",
        "timezone": tz_name,
        "forecast_days": 1,
    }
    resp = await http.get(URL, params=params, timeout=10)
    resp.raise_for_status()
    return parse(resp.json())


def summary(w: DayWeather) -> str:
    return (
        f"Sabah {w.t_morning:.0f}° → akşam {w.t_evening:.0f}° "
        f"(en düşük {w.t_min:.0f}°, en yüksek {w.t_max:.0f}°), "
        f"yağış %{w.rain_prob}, rüzgâr {w.wind_max:.0f} km/s"
    )
```

- [ ] **Step 4: `app/outfit.py`**
```python
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
        log.exception("Kıyafet önerisi Claude'dan alınamadı")
        return "\n".join(f"• {x}" for x in h) if h else "Hava ılıman, rahat giyinebilirsin."
```

- [ ] **Step 5: Testler geçsin**

Run: `.venv/Scripts/python -m pytest tests/test_weather.py tests/test_outfit.py -v`
Expected: tümü passed.

- [ ] **Step 6: Gerçek API ile duman testi**

Run:
```bash
.venv/Scripts/python -c "import asyncio,httpx;from app import weather;print(weather.summary(asyncio.run((lambda: (lambda c: weather.fetch(38.39,27.17,'Europe/Istanbul',c))(httpx.AsyncClient()))())))"
```
Expected: `Sabah …° → akşam …° …` satırı.

- [ ] **Step 7: Commit**
```bash
git add -A
git commit -m "feat: hava durumu ve kıyafet önerisi"
```

---

### Task 5: Piyasa + haberler

**Files:**
- Create: `app/finance.py`, `app/news.py`
- Test: `tests/test_finance.py`, `tests/test_news.py`

**Interfaces:**
- Produces: `finance.parse(data: dict) -> list[tuple[str, float]]`, `finance.format(rows) -> str`, `async finance.fetch(http) -> str`
- Produces: `news.parse(xml: str, limit: int = 5) -> list[str]`, `async news.fetch(http) -> str`

- [ ] **Step 1: Gerçek format doğrulaması**

Run: `curl -s https://finans.truncgil.com/v4/today.json | head -c 600`
Expected: `"USD": {..., "Selling": ...}`, `"EUR"`, `"GRA"` anahtarları. Anahtar adları veya `Selling` alanının tipi (sayı / `"41,23"` gibi string) farklıysa aşağıdaki `KEYS` ve `_num` ile test fixture'ını gerçek çıktıya göre düzelt.

- [ ] **Step 2: Failing testler**

`tests/test_finance.py`:
```python
import pytest

from app.finance import format, parse


def test_parse_numbers_and_strings():
    data = {
        "USD": {"Selling": 41.2345},
        "EUR": {"Selling": "48,10"},
        "GRA": {"Selling": "4.312,55"},
    }
    assert parse(data) == [("Dolar", 41.2345), ("Euro", 48.10), ("Gram altın", 4312.55)]


def test_parse_skips_missing():
    assert parse({"USD": {"Selling": 41}}) == [("Dolar", 41.0)]


def test_parse_empty_raises():
    with pytest.raises(ValueError):
        parse({"Update_Date": "x"})


def test_format():
    assert format([("Dolar", 41.2345), ("Gram altın", 4312.5)]) == "Dolar: 41.23 ₺\nGram altın: 4312.50 ₺"
```

`tests/test_news.py`:
```python
import pytest

from app.news import parse

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Birinci haber</title></item>
<item><title>İkinci haber</title></item>
<item><title>Üçüncü haber</title></item>
</channel></rss>"""


def test_parse_limit():
    assert parse(RSS, limit=2) == ["Birinci haber", "İkinci haber"]


def test_parse_empty_raises():
    with pytest.raises(ValueError):
        parse("<rss><channel></channel></rss>")
```

- [ ] **Step 3: Düştüğünü gör**

Run: `.venv/Scripts/python -m pytest tests/test_finance.py tests/test_news.py -v`
Expected: FAIL — modüller yok.

- [ ] **Step 4: `app/finance.py`**
```python
URL = "https://finans.truncgil.com/v4/today.json"
KEYS = {"USD": "Dolar", "EUR": "Euro", "GRA": "Gram altın"}


def _num(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).replace(".", "").replace(",", "."))


def parse(data: dict) -> list[tuple[str, float]]:
    rows = [(label, _num(data[key]["Selling"])) for key, label in KEYS.items() if "Selling" in data.get(key, {})]
    if not rows:
        raise ValueError("Piyasa verisi beklenen formatta değil")
    return rows


def format(rows: list[tuple[str, float]]) -> str:
    return "\n".join(f"{label}: {value:.2f} ₺" for label, value in rows)


async def fetch(http) -> str:
    resp = await http.get(URL, timeout=10)
    resp.raise_for_status()
    return format(parse(resp.json()))
```

- [ ] **Step 5: `app/news.py`**
```python
import feedparser

FEED = "https://feeds.bbci.co.uk/turkce/rss.xml"


def parse(xml: str, limit: int = 5) -> list[str]:
    titles = [e.title for e in feedparser.parse(xml).entries[:limit] if getattr(e, "title", "")]
    if not titles:
        raise ValueError("Haber bulunamadı")
    return titles


async def fetch(http) -> str:
    resp = await http.get(FEED, timeout=10, follow_redirects=True)
    resp.raise_for_status()
    return "\n".join(f"• {t}" for t in parse(resp.text))
```

- [ ] **Step 6: Testler geçsin**

Run: `.venv/Scripts/python -m pytest tests/test_finance.py tests/test_news.py -v`
Expected: tümü passed.

- [ ] **Step 7: Commit**
```bash
git add -A
git commit -m "feat: piyasa ve haber kaynakları"
```

---

### Task 6: Ders programı (`schedule.py`)

**Files:**
- Create: `app/schedule.py`
- Test: `tests/test_schedule.py`

**Interfaces:**
- Consumes: `LLM.ask_json` (Task 2), `DB.get_schedule` / `all_schedules` (Task 3; testte `FakeDB`)
- Produces:
  - `WEEKDAYS: list[str]` = `["pazartesi","salı","çarşamba","perşembe","cuma"]`, `WEEKEND = ["cumartesi","pazar"]`, `ALL_DAYS = WEEKDAYS + WEEKEND`
  - `class ScheduleError(ValueError)`
  - `validate_okul(data) -> dict[str, list[dict]]`, `validate_dershane(data) -> list[dict]` (ders öğesi: `{"saat": str, "ders": str}`)
  - `async read_photo(image: bytes, kind: str, llm) -> dict | list` (`kind` ∈ `"okul"`, `"dershane"`)
  - `day_key(d: date) -> str`
  - `async lessons_for(d: date, db) -> list[dict] | None`
  - `format_lessons(lessons: list[dict] | None) -> str`, `format_okul(data: dict) -> str`, `format_all(schedules: dict) -> str`

- [ ] **Step 1: Failing test** — `tests/test_schedule.py`
```python
from datetime import date

import pytest

from app.schedule import (
    ScheduleError, day_key, format_all, format_lessons, lessons_for, read_photo, validate_dershane, validate_okul,
)
from tests.fakes import FakeDB, FakeLLM

OKUL = {
    "pazartesi": [{"saat": "08:30", "ders": "Matematik"}, {"saat": "", "ders": "Fizik"}],
    "salı": [],
    "çarşamba": [{"saat": "09:20", "ders": "Kimya"}],
    "perşembe": [],
    "cuma": [{"saat": "08:30", "ders": "Tarih"}],
}


def test_validate_okul_fills_missing_days():
    out = validate_okul({"pazartesi": [{"saat": 830, "ders": " Mat "}]})
    assert out["pazartesi"] == [{"saat": "830", "ders": "Mat"}]
    assert out["cuma"] == []


def test_validate_okul_all_empty_raises():
    with pytest.raises(ScheduleError):
        validate_okul({"pazartesi": []})


def test_validate_bad_item_raises():
    with pytest.raises(ScheduleError):
        validate_okul({"pazartesi": [{"saat": "08:30"}]})
    with pytest.raises(ScheduleError):
        validate_dershane({"ders": "Fizik"})


def test_day_key():
    assert day_key(date(2026, 10, 12)) == "pazartesi"
    assert day_key(date(2026, 10, 17)) == "cumartesi"
    assert day_key(date(2026, 10, 18)) == "pazar"


async def test_lessons_weekday_from_okul():
    db = FakeDB({("okul", ""): OKUL})
    assert await lessons_for(date(2026, 10, 14), db) == [{"saat": "09:20", "ders": "Kimya"}]


async def test_lessons_saturday_from_dershane():
    sat = [{"saat": "10:00", "ders": "Türkçe"}]
    db = FakeDB({("okul", ""): OKUL, ("dershane", "cumartesi"): sat})
    assert await lessons_for(date(2026, 10, 17), db) == sat


async def test_lessons_missing_schedule_is_none():
    assert await lessons_for(date(2026, 10, 18), FakeDB({("okul", ""): OKUL})) is None
    assert await lessons_for(date(2026, 10, 12), FakeDB()) is None


def test_format_lessons():
    assert format_lessons(None).startswith("Bu gün için kayıtlı program yok")
    assert format_lessons([]) == "Bugün ders yok 🎉"
    assert format_lessons(OKUL["pazartesi"]) == "• 08:30 Matematik\n• Fizik"


def test_format_all_marks_missing():
    text = format_all({"okul": OKUL, "cumartesi": None, "pazar": [{"saat": "", "ders": "Mat"}]})
    assert "Pazartesi:\n• 08:30 Matematik" in text
    assert "Dershane Cumartesi:\nBu gün için kayıtlı program yok" in text
    assert "Dershane Pazar:\n• Mat" in text


async def test_read_photo_dershane():
    llm = FakeLLM(reply='```json\n[{"saat": "09:00", "ders": "Fizik"}]\n```')
    assert await read_photo(b"img", "dershane", llm) == [{"saat": "09:00", "ders": "Fizik"}]
    assert llm.calls[0]["image"] == b"img"


async def test_read_photo_okul_unreadable_raises():
    with pytest.raises(Exception):
        await read_photo(b"img", "okul", FakeLLM(reply="Fotoğraf çok bulanık."))
```

- [ ] **Step 2: Düştüğünü gör**

Run: `.venv/Scripts/python -m pytest tests/test_schedule.py -v`
Expected: FAIL — modül yok.

- [ ] **Step 3: `app/schedule.py`**
```python
from datetime import date

WEEKDAYS = ["pazartesi", "salı", "çarşamba", "perşembe", "cuma"]
WEEKEND = ["cumartesi", "pazar"]
ALL_DAYS = WEEKDAYS + WEEKEND

OKUL_PROMPT = (
    "Bu bir haftalık okul ders programı fotoğrafı. Sadece JSON döndür, başka bir şey yazma. Biçim: "
    '{"pazartesi": [{"saat": "08:30", "ders": "Matematik"}], "salı": [], "çarşamba": [], "perşembe": [], "cuma": []}. '
    "Ders sırasını koru. Saat okunamıyorsa boş string yaz. Boş günler için boş liste ver."
)
DERSHANE_PROMPT = (
    "Bu tek bir günün dershane ders programı fotoğrafı. Sadece JSON dizi döndür, başka bir şey yazma. Biçim: "
    '[{"saat": "09:00", "ders": "Fizik"}]. Ders sırasını koru. Saat okunamıyorsa boş string yaz.'
)


class ScheduleError(ValueError):
    pass


def _lessons(items) -> list[dict]:
    if not isinstance(items, list):
        raise ScheduleError("Ders listesi bekleniyordu")
    out = []
    for item in items:
        if not isinstance(item, dict) or not str(item.get("ders", "")).strip():
            raise ScheduleError(f"Geçersiz ders kaydı: {item}")
        out.append({"saat": str(item.get("saat", "")).strip(), "ders": str(item["ders"]).strip()})
    return out


def validate_okul(data) -> dict[str, list[dict]]:
    if not isinstance(data, dict):
        raise ScheduleError("Okul programı gün → ders listesi biçiminde olmalı")
    result = {d: _lessons(data.get(d, [])) for d in WEEKDAYS}
    if not any(result.values()):
        raise ScheduleError("Programda hiç ders bulunamadı")
    return result


def validate_dershane(data) -> list[dict]:
    lessons = _lessons(data)
    if not lessons:
        raise ScheduleError("Programda hiç ders bulunamadı")
    return lessons


async def read_photo(image: bytes, kind: str, llm):
    if kind == "okul":
        return validate_okul(await llm.ask_json(OKUL_PROMPT, image=image))
    return validate_dershane(await llm.ask_json(DERSHANE_PROMPT, image=image))


def day_key(d: date) -> str:
    return ALL_DAYS[d.weekday()]


async def lessons_for(d: date, db):
    key = day_key(d)
    if key in WEEKDAYS:
        okul = await db.get_schedule("okul", "")
        return None if okul is None else okul.get(key, [])
    return await db.get_schedule("dershane", key)


def format_lessons(lessons) -> str:
    if lessons is None:
        return "Bu gün için kayıtlı program yok. Fotoğrafını atarsan kaydederim."
    if not lessons:
        return "Bugün ders yok 🎉"
    return "\n".join(f"• {l['saat'] + ' ' if l['saat'] else ''}{l['ders']}" for l in lessons)


def format_okul(data: dict) -> str:
    return "\n".join(f"{d.capitalize()}:\n{format_lessons(data.get(d, []))}" for d in WEEKDAYS)


def format_all(schedules: dict) -> str:
    okul = schedules.get("okul")
    parts = ["🏫 Okul (hafta içi)", format_okul(okul) if okul is not None else "Kayıtlı değil"]
    for d in WEEKEND:
        parts.append(f"📘 Dershane {d.capitalize()}:\n{format_lessons(schedules.get(d))}")
    return "\n".join(parts)
```

- [ ] **Step 4: Testler geçsin**

Run: `.venv/Scripts/python -m pytest tests/test_schedule.py -v`
Expected: tümü passed.

- [ ] **Step 5: Commit**
```bash
git add -A
git commit -m "feat: ders programı okuma ve gün seçimi"
```

---

### Task 7: Hatırlatıcı ayrıştırma (`reminders.py`)

**Files:**
- Create: `app/reminders.py`
- Test: `tests/test_reminders.py`

**Interfaces:**
- Consumes: `LLM.ask_json` (Task 2), `schedule.ALL_DAYS` (Task 6)
- Produces: `class ReminderError(ValueError)`, `parse_result(data, now: datetime) -> tuple[datetime, str]`, `async parse(message: str, now: datetime, llm) -> tuple[datetime, str]`, `format_when(dt: datetime) -> str`

- [ ] **Step 1: Failing test** — `tests/test_reminders.py`
```python
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.reminders import ReminderError, format_when, parse, parse_result
from tests.fakes import FakeLLM

TZ = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 10, 9, 20, 0, tzinfo=TZ)


def test_naive_time_gets_local_tz():
    when, text = parse_result({"when": "2026-10-10T15:00", "text": "faturayı öde"}, NOW)
    assert when == datetime(2026, 10, 10, 15, 0, tzinfo=TZ)
    assert text == "faturayı öde"


def test_aware_time_kept():
    when, _ = parse_result({"when": "2026-10-10T12:00+00:00", "text": "x"}, NOW)
    assert when.astimezone(TZ).hour == 15


def test_past_rejected():
    with pytest.raises(ReminderError, match="geçmişte"):
        parse_result({"when": "2026-10-09T19:59", "text": "x"}, NOW)


@pytest.mark.parametrize("data", [{}, {"when": "yarın", "text": "x"}, {"when": "2026-10-10T15:00", "text": " "}, []])
def test_bad_payload_rejected(data):
    with pytest.raises(ReminderError):
        parse_result(data, NOW)


async def test_parse_sends_now_and_day():
    llm = FakeLLM(reply='```json\n{"when": "2026-10-10T15:00", "text": "faturayı öde"}\n```')
    when, text = await parse("yarın 15'te faturayı hatırlat", NOW, llm)
    assert when.hour == 15 and text == "faturayı öde"
    assert "2026-10-09 20:00" in llm.calls[0]["prompt"] and "cuma" in llm.calls[0]["prompt"]


def test_format_when():
    assert format_when(datetime(2026, 10, 10, 15, 0, tzinfo=TZ)) == "10.10.2026 15:00"
```

- [ ] **Step 2: Düştüğünü gör**

Run: `.venv/Scripts/python -m pytest tests/test_reminders.py -v`
Expected: FAIL — modül yok.

- [ ] **Step 3: `app/reminders.py`**
```python
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
    if when.tzinfo is None:
        when = when.replace(tzinfo=now.tzinfo)
    if when <= now:
        raise ReminderError(f"Bu zaman geçmişte: {format_when(when.astimezone(now.tzinfo))}")
    return when, text


async def parse(message: str, now: datetime, llm) -> tuple[datetime, str]:
    prompt = f"Şu an: {now:%Y-%m-%d %H:%M} ({ALL_DAYS[now.weekday()]}). İstek: {message}"
    return parse_result(await llm.ask_json(prompt, SYSTEM), now)


def format_when(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y %H:%M")
```

- [ ] **Step 4: Testler geçsin**

Run: `.venv/Scripts/python -m pytest tests/test_reminders.py -v`
Expected: tümü passed.

- [ ] **Step 5: Commit**
```bash
git add -A
git commit -m "feat: doğal dille hatırlatıcı ayrıştırma"
```

---

### Task 8: Sesli not, sohbet, mesaj bölme

**Files:**
- Create: `app/notes.py`, `app/chat.py`, `app/textutil.py`
- Test: `tests/test_notes.py`, `tests/test_chat.py`, `tests/test_textutil.py`

**Interfaces:**
- Consumes: `LLM.ask` (Task 2), `DB.recent_notes` / `all_schedules` (Task 3), `schedule.format_all`, `schedule.ALL_DAYS` (Task 6)
- Produces: `notes.Transcriber(api_key: str, client=None)` with `async transcribe(audio: bytes, filename: str = "voice.ogg") -> str`; `chat.build_context(notes: list[dict], schedules: dict, now: datetime) -> str`; `async chat.answer(question: str, db, llm, now: datetime) -> str`; `textutil.split_message(text: str, limit: int = 4096) -> list[str]`

- [ ] **Step 1: Failing testler**

`tests/test_textutil.py`:
```python
from app.textutil import split_message


def test_short_untouched():
    assert split_message("merhaba") == ["merhaba"]


def test_splits_on_newlines():
    text = "\n".join(["a" * 30] * 10)
    parts = split_message(text, limit=100)
    assert all(len(p) <= 100 for p in parts)
    assert "\n".join(parts) == text


def test_hard_splits_long_line():
    parts = split_message("x" * 250, limit=100)
    assert [len(p) for p in parts] == [100, 100, 50]


def test_empty():
    assert split_message("") == [""]
```

`tests/test_notes.py`:
```python
from types import SimpleNamespace

import pytest

from app.notes import Transcriber


class _Tr:
    def __init__(self, text):
        self.text = text
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(text=self.text)


def _client(text):
    tr = _Tr(text)
    return tr, SimpleNamespace(audio=SimpleNamespace(transcriptions=tr))


async def test_transcribe_turkish():
    tr, client = _client("  süt almayı unutma ")
    assert await Transcriber("k", client=client).transcribe(b"ogg") == "süt almayı unutma"
    assert tr.kwargs["model"] == "whisper-large-v3"
    assert tr.kwargs["language"] == "tr"
    assert tr.kwargs["file"] == ("voice.ogg", b"ogg")


async def test_empty_transcript_raises():
    _, client = _client("   ")
    with pytest.raises(ValueError):
        await Transcriber("k", client=client).transcribe(b"ogg")
```

`tests/test_chat.py`:
```python
from datetime import datetime
from zoneinfo import ZoneInfo

from app.chat import answer, build_context
from tests.fakes import FakeDB, FakeLLM

TZ = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 10, 9, 20, 0, tzinfo=TZ)
NOTES = [{"id": 1, "text": "Ahmet'e kitabı geri ver", "created_at": datetime(2026, 10, 5, 18, 30, tzinfo=TZ)}]


def test_context_has_date_notes_and_program():
    ctx = build_context(NOTES, {"okul": None, "cumartesi": None, "pazar": None}, NOW)
    assert "09.10.2026 20:00 (cuma)" in ctx
    assert "[05.10.2026 18:30] Ahmet'e kitabı geri ver" in ctx
    assert "🏫 Okul (hafta içi)" in ctx


def test_context_no_notes():
    assert "Henüz not yok." in build_context([], {}, NOW)


async def test_answer_passes_context_as_system():
    llm = FakeLLM(reply=" Ahmet'e kitabı vermen gerekiyordu. ")
    out = await answer("geçen hafta ne demiştim?", FakeDB(notes=NOTES), llm, NOW)
    assert out == "Ahmet'e kitabı vermen gerekiyordu."
    assert "Ahmet'e kitabı geri ver" in llm.calls[0]["system"]
    assert llm.calls[0]["prompt"] == "geçen hafta ne demiştim?"
```

- [ ] **Step 2: Düştüğünü gör**

Run: `.venv/Scripts/python -m pytest tests/test_textutil.py tests/test_notes.py tests/test_chat.py -v`
Expected: FAIL — modüller yok.

- [ ] **Step 3: `app/textutil.py`**
```python
def split_message(text: str, limit: int = 4096) -> list[str]:
    parts, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    parts.append(current)
    return parts
```

- [ ] **Step 4: `app/notes.py`**
```python
from groq import AsyncGroq

MODEL = "whisper-large-v3"


class Transcriber:
    def __init__(self, api_key: str, client=None):
        self.client = client or AsyncGroq(api_key=api_key, timeout=30)

    async def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        resp = await self.client.audio.transcriptions.create(file=(filename, audio), model=MODEL, language="tr")
        text = resp.text.strip()
        if not text:
            raise ValueError("Ses boş ya da anlaşılamadı")
        return text
```

- [ ] **Step 5: `app/chat.py`**
```python
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
```

- [ ] **Step 6: Testler geçsin**

Run: `.venv/Scripts/python -m pytest tests/test_textutil.py tests/test_notes.py tests/test_chat.py -v`
Expected: tümü passed.

- [ ] **Step 7: Commit**
```bash
git add -A
git commit -m "feat: sesli not, bağlamlı sohbet ve mesaj bölme"
```

---

### Task 9: Sabah özeti (`briefing.py`)

**Files:**
- Create: `app/briefing.py`
- Test: `tests/test_briefing.py`

**Interfaces:**
- Consumes: `weather.fetch`, `weather.summary` (Task 4), `outfit.advice` (Task 4), `finance.fetch`, `news.fetch` (Task 5), `schedule.lessons_for`, `schedule.format_lessons` (Task 6)
- Produces: `Sources` (dataclass: `weather`, `lessons`, `finance`, `news` — her biri `Callable[[], Awaitable[str]]`), `async build(today: date, src: Sources) -> str`, `make_sources(cfg, db, llm, http, today: date) -> Sources`

- [ ] **Step 1: Failing test** — `tests/test_briefing.py`
```python
from datetime import date

from app.briefing import Sources, build


def _ok(text):
    async def f():
        return text
    return f


async def _boom():
    raise RuntimeError("api down")


async def test_all_sections_in_order():
    src = Sources(weather=_ok("Güneşli"), lessons=_ok("• Mat"), finance=_ok("Dolar: 41"), news=_ok("• Haber"))
    text = await build(date(2026, 10, 9), src)
    assert text.startswith("Günaydın Kayra! ☀️ 9 Ekim Cuma")
    assert text.index("🌤 Hava\nGüneşli") < text.index("📚 Bugünün dersleri\n• Mat") < text.index("💱 Piyasa") < text.index("📰 Haberler")


async def test_failed_section_does_not_break_others(caplog):
    src = Sources(weather=_boom, lessons=_ok("• Mat"), finance=_boom, news=_ok("• Haber"))
    text = await build(date(2026, 10, 9), src)
    assert "🌤 Hava\n⚠️ Hava alınamadı" in text
    assert "💱 Piyasa\n⚠️ Piyasa alınamadı" in text
    assert "• Mat" in text and "• Haber" in text
    assert "api down" in caplog.text
```

- [ ] **Step 2: Düştüğünü gör**

Run: `.venv/Scripts/python -m pytest tests/test_briefing.py -v`
Expected: FAIL — modül yok.

- [ ] **Step 3: `app/briefing.py`**
```python
import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from app import finance, news, outfit, weather
from app.schedule import format_lessons, lessons_for

log = logging.getLogger(__name__)

MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
SECTIONS = [
    ("weather", "🌤 Hava", "Hava"),
    ("lessons", "📚 Bugünün dersleri", "Ders programı"),
    ("finance", "💱 Piyasa", "Piyasa"),
    ("news", "📰 Haberler", "Haberler"),
]

Source = Callable[[], Awaitable[str]]


@dataclass
class Sources:
    weather: Source
    lessons: Source
    finance: Source
    news: Source


async def build(today: date, src: Sources) -> str:
    results = await asyncio.gather(*(getattr(src, attr)() for attr, _, _ in SECTIONS), return_exceptions=True)
    parts = [f"Günaydın Kayra! ☀️ {today.day} {MONTHS[today.month - 1]} {DAYS[today.weekday()]}"]
    for (attr, title, label), result in zip(SECTIONS, results):
        if isinstance(result, BaseException):
            log.error("Özet bölümü alınamadı: %s", attr, exc_info=result)
            result = f"⚠️ {label} alınamadı"
        parts.append(f"{title}\n{result}")
    return "\n\n".join(parts)


def make_sources(cfg, db, llm, http, today: date) -> Sources:
    async def weather_section() -> str:
        w = await weather.fetch(cfg.lat, cfg.lon, cfg.tz.key, http)
        return f"{weather.summary(w)}\n👕 {await outfit.advice(w, llm)}"

    async def lessons_section() -> str:
        return format_lessons(await lessons_for(today, db))

    return Sources(
        weather=weather_section,
        lessons=lessons_section,
        finance=lambda: finance.fetch(http),
        news=lambda: news.fetch(http),
    )
```

- [ ] **Step 4: Testler geçsin**

Run: `.venv/Scripts/python -m pytest tests/test_briefing.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**
```bash
git add -A
git commit -m "feat: sabah özeti birleştirici"
```

---

### Task 10: Telegram botu (`bot.py`)

**Files:**
- Create: `app/bot.py`
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: tüm önceki modüller. `bot_data` anahtarları: `cfg: Config`, `db: DB`, `llm: LLM`, `transcriber: Transcriber`, `http: httpx.AsyncClient`
- Produces: `async gate(update, context) -> None` (sahibi değilse `ApplicationHandlerStop`), `register(app: Application) -> None`, `schedule_reminder(job_queue, reminder_id: int, when: datetime, text: str) -> None`, `async restore_reminders(app: Application) -> None`, `async send_text(bot, chat_id: int, text: str) -> None`

- [ ] **Step 1: Failing test** — `tests/test_bot.py`
```python
from types import SimpleNamespace

import pytest
from telegram.ext import ApplicationHandlerStop

from app.bot import gate


def _ctx():
    return SimpleNamespace(bot_data={"cfg": SimpleNamespace(owner_id=42)})


async def test_gate_allows_owner():
    assert await gate(SimpleNamespace(effective_user=SimpleNamespace(id=42)), _ctx()) is None


@pytest.mark.parametrize("user", [SimpleNamespace(id=7), None])
async def test_gate_blocks_others(user):
    with pytest.raises(ApplicationHandlerStop):
        await gate(SimpleNamespace(effective_user=user), _ctx())
```

- [ ] **Step 2: Düştüğünü gör**

Run: `.venv/Scripts/python -m pytest tests/test_bot.py -v`
Expected: FAIL — modül yok.

- [ ] **Step 3: `app/bot.py`**
```python
import logging
from datetime import date, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler,
    TypeHandler, filters,
)

from app import briefing, chat, reminders, schedule
from app.textutil import split_message

log = logging.getLogger(__name__)

HELP = (
    "Merhaba Kayra! Yapabileceklerim:\n"
    "📷 Ders programı fotoğrafı at → kaydederim\n"
    "🎤 Sesli mesaj at → nota çeviririm\n"
    "⏰ \"yarın 15'te faturayı hatırlat\" yaz → hatırlatırım\n"
    "💬 Başka bir şey yaz → notlarına ve programına bakarak cevaplarım\n\n"
    "/ozet sabah özetini şimdi gönder\n"
    "/program kayıtlı programlar\n"
    "/notlar son notlar\n"
    "/hatirlat <metin>\n"
    "/hatirlaticilar bekleyen hatırlatıcılar\n"
    "/sil <id> hatırlatıcıyı sil"
)
KIND_BUTTONS = InlineKeyboardMarkup([
    [InlineKeyboardButton("🏫 Okul (hafta içi)", callback_data="kind:okul:")],
    [InlineKeyboardButton("📘 Dershane Cumartesi", callback_data="kind:dershane:cumartesi")],
    [InlineKeyboardButton("📘 Dershane Pazar", callback_data="kind:dershane:pazar")],
])
CONFIRM_BUTTONS = InlineKeyboardMarkup([[
    InlineKeyboardButton("✅ Kaydet", callback_data="save"),
    InlineKeyboardButton("🔁 Tekrar oku", callback_data="retry"),
]])


def _deps(context):
    return context.bot_data


def _now(context) -> datetime:
    return datetime.now(_deps(context)["cfg"].tz)


async def send_text(bot, chat_id: int, text: str) -> None:
    for part in split_message(text):
        await bot.send_message(chat_id, part)


async def gate(update, context) -> None:
    user = update.effective_user
    if user is None or user.id != context.bot_data["cfg"].owner_id:
        raise ApplicationHandlerStop


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP)


async def send_briefing(context: ContextTypes.DEFAULT_TYPE) -> None:
    d = _deps(context)
    today = _now(context).date()
    src = briefing.make_sources(d["cfg"], d["db"], d["llm"], d["http"], today)
    await send_text(context.bot, d["cfg"].owner_id, await briefing.build(today, src))


async def ozet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_briefing(context)


async def program(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = schedule.format_all(await _deps(context)["db"].all_schedules())
    await send_text(context.bot, update.effective_chat.id, text)


async def notlar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = _deps(context)
    notes = await d["db"].recent_notes(10)
    if not notes:
        await update.message.reply_text("Henüz not yok.")
        return
    lines = [f"[{n['created_at'].astimezone(d['cfg'].tz):%d.%m %H:%M}] {n['text']}" for n in notes]
    await send_text(context.bot, update.effective_chat.id, "\n".join(lines))


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    file = await update.message.photo[-1].get_file()
    context.user_data["photo"] = bytes(await file.download_as_bytearray())
    await update.message.reply_text("Bu hangi program?", reply_markup=KIND_BUTTONS)


async def _read_and_preview(query, context) -> None:
    kind, day = context.user_data["kind"]
    await query.edit_message_text("Okuyorum… ⏳")
    try:
        data = await schedule.read_photo(context.user_data["photo"], kind, _deps(context)["llm"])
    except Exception:
        log.exception("Program fotoğrafı okunamadı")
        await query.edit_message_text("Programı okuyamadım, daha net bir fotoğraf atar mısın?")
        return
    context.user_data["parsed"] = data
    preview = schedule.format_okul(data) if kind == "okul" else schedule.format_lessons(data)
    await query.edit_message_text(f"Şunu okudum:\n\n{preview[:3800]}\n\nDoğru mu?", reply_markup=CONFIRM_BUTTONS)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if "photo" not in context.user_data:
        await query.edit_message_text("Fotoğraf bulunamadı, tekrar atar mısın?")
        return
    if query.data.startswith("kind:"):
        _, kind, day = query.data.split(":")
        context.user_data["kind"] = (kind, day)
        await _read_and_preview(query, context)
    elif query.data == "retry":
        await _read_and_preview(query, context)
    elif query.data == "save":
        kind, day = context.user_data["kind"]
        await _deps(context)["db"].save_schedule(kind, day, context.user_data["parsed"])
        context.user_data.clear()
        await query.edit_message_text("✅ Program kaydedildi.")


async def voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = _deps(context)
    file = await update.message.voice.get_file()
    audio = bytes(await file.download_as_bytearray())
    try:
        text = await d["transcriber"].transcribe(audio)
    except Exception:
        log.exception("Ses yazıya çevrilemedi")
        await update.message.reply_text("Sesi yazıya çeviremedim. Ses mesajın sohbette duruyor, bana tekrar iletebilirsin.")
        return
    await d["db"].add_note(text, "ses")
    await update.message.reply_text(f"📝 Kaydedildi: {text}")


async def _fire_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    reminder_id, text = context.job.data
    d = _deps(context)
    await context.bot.send_message(d["cfg"].owner_id, f"⏰ {text}")
    await d["db"].mark_sent(reminder_id)


def schedule_reminder(job_queue, reminder_id: int, when: datetime, text: str) -> None:
    job_queue.run_once(_fire_reminder, when=when, data=(reminder_id, text), name=f"rem-{reminder_id}")


async def restore_reminders(app: Application) -> None:
    d = app.bot_data
    now = datetime.now(d["cfg"].tz)
    for r in await d["db"].pending_reminders():
        if r["due_at"] <= now:
            await app.bot.send_message(d["cfg"].owner_id, f"⏰ (gecikmeli) {r['text']}")
            await d["db"].mark_sent(r["id"])
        else:
            schedule_reminder(app.job_queue, r["id"], r["due_at"], r["text"])


async def _create_reminder(update: Update, context, message: str) -> None:
    d = _deps(context)
    try:
        when, text = await reminders.parse(message, _now(context), d["llm"])
    except reminders.ReminderError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return
    reminder_id = await d["db"].add_reminder(text, when)
    schedule_reminder(context.job_queue, reminder_id, when, text)
    await update.message.reply_text(f"⏰ Tamam! {reminders.format_when(when)} — {text} (#{reminder_id})")


async def hatirlat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Kullanım: /hatirlat yarın 15'te faturayı öde")
        return
    await _create_reminder(update, context, " ".join(context.args))


async def hatirlaticilar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = _deps(context)
    pending = await d["db"].pending_reminders()
    if not pending:
        await update.message.reply_text("Bekleyen hatırlatıcı yok.")
        return
    lines = [f"#{r['id']} {reminders.format_when(r['due_at'].astimezone(d['cfg'].tz))} — {r['text']}" for r in pending]
    await send_text(context.bot, update.effective_chat.id, "\n".join(lines))


async def sil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].lstrip("#").isdigit():
        await update.message.reply_text("Kullanım: /sil 3")
        return
    reminder_id = int(context.args[0].lstrip("#"))
    for job in context.job_queue.get_jobs_by_name(f"rem-{reminder_id}"):
        job.schedule_removal()
    deleted = await _deps(context)["db"].delete_reminder(reminder_id)
    await update.message.reply_text("🗑 Silindi." if deleted else "Bu numarada hatırlatıcı yok.")


async def text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message.text
    if "hatırlat" in message.lower():
        await _create_reminder(update, context, message)
        return
    d = _deps(context)
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    reply = await chat.answer(message, d["db"], d["llm"], _now(context))
    await send_text(context.bot, update.effective_chat.id, reply)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Beklenmeyen hata", exc_info=context.error)
    try:
        await context.bot.send_message(context.bot_data["cfg"].owner_id, f"⚠️ Bir hata oldu: {context.error}")
    except Exception:
        log.exception("Hata mesajı da gönderilemedi")


def register(app: Application) -> None:
    app.add_handler(TypeHandler(Update, gate), group=-1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ozet", ozet))
    app.add_handler(CommandHandler("program", program))
    app.add_handler(CommandHandler("notlar", notlar))
    app.add_handler(CommandHandler("hatirlat", hatirlat))
    app.add_handler(CommandHandler("hatirlaticilar", hatirlaticilar))
    app.add_handler(CommandHandler("sil", sil))
    app.add_handler(MessageHandler(filters.PHOTO, photo))
    app.add_handler(MessageHandler(filters.VOICE, voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_error_handler(on_error)
    cfg = app.bot_data["cfg"]
    app.job_queue.run_daily(send_briefing, time=cfg.briefing_time, name="sabah-ozeti")
```

- [ ] **Step 4: Testler geçsin**

Run: `.venv/Scripts/python -m pytest -v`
Expected: tüm testler passed (DB testleri `TEST_DATABASE_URL` yoksa skipped).

- [ ] **Step 5: Commit**
```bash
git add -A
git commit -m "feat: Telegram handler'ları, gate ve hatırlatıcı job'ları"
```

---

### Task 11: Giriş noktası, health endpoint, deploy

**Files:**
- Create: `app/main.py`, `render.yaml`, `README.md`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `config.load`, `DB.connect`, `LLM`, `Transcriber`, `bot.register`, `bot.restore_reminders`
- Produces: `start_health_server(port: int) -> ThreadingHTTPServer`, `main() -> None`

- [ ] **Step 1: Failing test** — `tests/test_main.py`
```python
import urllib.request

from app.main import start_health_server


def test_health_returns_ok():
    server = start_health_server(0)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            assert resp.status == 200 and resp.read() == b"ok"
    finally:
        server.shutdown()
```

- [ ] **Step 2: Düştüğünü gör**

Run: `.venv/Scripts/python -m pytest tests/test_main.py -v`
Expected: FAIL — modül yok.

- [ ] **Step 3: `app/main.py`**
```python
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from telegram.ext import Application

from app import bot, config
from app.db import DB
from app.llm import LLM
from app.notes import Transcriber

log = logging.getLogger(__name__)


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def start_health_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), _Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def _post_init(app: Application) -> None:
    cfg = app.bot_data["cfg"]
    app.bot_data["db"] = await DB.connect(cfg.database_url)
    app.bot_data["http"] = httpx.AsyncClient()
    await bot.restore_reminders(app)
    log.info("Bot hazır")


async def _post_shutdown(app: Application) -> None:
    if "http" in app.bot_data:
        await app.bot_data["http"].aclose()
    if "db" in app.bot_data:
        await app.bot_data["db"].close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = config.load()
    start_health_server(cfg.port)
    app = (
        Application.builder()
        .token(cfg.telegram_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data.update(cfg=cfg, llm=LLM(cfg.anthropic_key), transcriber=Transcriber(cfg.groq_key))
    bot.register(app)
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Testler geçsin**

Run: `.venv/Scripts/python -m pytest -v`
Expected: tümü passed / DB skipped.

- [ ] **Step 5: `render.yaml`**
```yaml
services:
  - type: web
    name: gunluk-ajan
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: python -m app.main
    healthCheckPath: /health
    envVars:
      - key: PYTHON_VERSION
        value: 3.12.7
      - key: TZ
        value: Europe/Istanbul
      - key: LAT
        value: "38.39"
      - key: LON
        value: "27.17"
      - key: BRIEFING_TIME
        value: "07:00"
      - key: TELEGRAM_TOKEN
        sync: false
      - key: OWNER_ID
        sync: false
      - key: ANTHROPIC_API_KEY
        sync: false
      - key: GROQ_API_KEY
        sync: false
      - key: DATABASE_URL
        sync: false
```

- [ ] **Step 6: `README.md`**
````markdown
# Günlük Ajan

Kayra'nın kişisel Telegram asistanı: sabah özeti, ders programı, sesli not, hatırlatıcı, AI sohbet.

## Kurulum
1. @BotFather → `/newbot` → token al.
2. @userinfobot → kendi Telegram ID'ni öğren (`OWNER_ID`).
3. neon.tech → ücretsiz proje → bağlantı adresi (`DATABASE_URL`).
4. console.anthropic.com → API anahtarı; console.groq.com → API anahtarı.
5. `.env.example` → `.env` kopyala, doldur.

## Yerelde çalıştırma
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
set -a; source .env; set +a
.venv/Scripts/python -m app.main
```

## Test
```bash
.venv/Scripts/python -m pytest -v
```
DB testleri için `TEST_DATABASE_URL` ayarla (ayrı bir Neon branch'i önerilir).

## Render
1. Repoyu GitHub'a it, Render → New → Blueprint → bu repo (`render.yaml` okunur).
2. Gizli değişkenleri Render panelinden gir.
3. cron-job.org → her 10 dakikada `https://<servis>.onrender.com/health` GET (ücretsiz plan uyumasın diye).
4. Yerel botu kapat: aynı token ile iki yerde polling çakışır.
````

- [ ] **Step 7: Yerel duman testi (gerçek anahtarlarla)**

Run: `set -a; source .env; set +a; .venv/Scripts/python -m app.main`
Telegram'dan sırayla kontrol et:
1. `/start` → yardım metni
2. `/ozet` → hava + 👕 öneri + ders bölümü ("kayıtlı program yok") + piyasa + haberler
3. Okul programı fotoğrafı → "🏫 Okul" → önizleme → ✅ → `/program` ile görünür
4. Dershane fotoğrafı → "📘 Dershane Cumartesi" → kaydet
5. Sesli mesaj → "📝 Kaydedildi: …"
6. "2 dakika sonra su içmeyi hatırlat" → 2 dk sonra ⏰ mesajı
7. "geçen gün ne not almıştım?" → notlara dayalı cevap
8. Başka bir hesaptan mesaj → cevap gelmemeli
9. Botu kapat, `/hatirlat 1 dakika sonra test` kur, 2 dk bekle, tekrar aç → "(gecikmeli) test"

Expected: 9 maddenin hepsi beklendiği gibi; terminalde traceback yok.

- [ ] **Step 8: Commit**
```bash
git add -A
git commit -m "feat: giriş noktası, health endpoint ve Render yapılandırması"
```
