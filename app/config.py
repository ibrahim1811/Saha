import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

REQUIRED = ["TELEGRAM_TOKEN", "OWNER_ID", "GROQ_API_KEY", "DATABASE_URL"]


@dataclass(frozen=True)
class Config:
    telegram_token: str
    owner_id: int
    groq_key: str
    llm_key: str
    llm_base_url: str
    llm_model: str
    llm_vision_model: str
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
        groq_key=env["GROQ_API_KEY"],
        llm_key=env.get("LLM_API_KEY") or env["GROQ_API_KEY"],
        llm_base_url=env.get("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"),
        llm_model=env.get("LLM_MODEL", "llama-3.3-70b-versatile"),
        llm_vision_model=env.get("LLM_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"),
        database_url=env["DATABASE_URL"],
        tz=tz,
        lat=float(env.get("LAT", "38.39")),
        lon=float(env.get("LON", "27.17")),
        briefing_time=time(int(hour), int(minute), tzinfo=tz),
        port=int(env.get("PORT", "10000")),
    )
