from datetime import time

import pytest

from app.config import load

BASE = {
    "TELEGRAM_TOKEN": "t",
    "OWNER_ID": "42",
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
    assert cfg.llm_key == "g"
    assert cfg.llm_base_url == "https://api.groq.com/openai/v1"
    assert cfg.llm_model == "openai/gpt-oss-120b"
    assert cfg.llm_vision_model == "qwen/qwen3.8-27b"


def test_load_overrides():
    cfg = load({
        **BASE,
        "BRIEFING_TIME": "06:45",
        "PORT": "8080",
        "LLM_API_KEY": "xai",
        "LLM_BASE_URL": "https://api.x.ai/v1/",
        "LLM_MODEL": "grok-4",
        "LLM_VISION_MODEL": "grok-4",
    })
    assert cfg.briefing_time.replace(tzinfo=None) == time(6, 45)
    assert cfg.port == 8080
    assert cfg.llm_key == "xai"
    assert cfg.llm_base_url == "https://api.x.ai/v1"
    assert cfg.llm_model == cfg.llm_vision_model == "grok-4"


def test_missing_vars_listed():
    with pytest.raises(RuntimeError) as e:
        load({"TELEGRAM_TOKEN": "t"})
    assert "OWNER_ID" in str(e.value) and "GROQ_API_KEY" in str(e.value)
