import pytest

from app.settings import DEFAULTS, SettingsError, merge, validate


def test_merge_defaults_with_env_time():
    s = merge(None, "06:30")
    assert s["briefing_time"] == "06:30"
    assert s["sections"] == {"weather": True, "lessons": True, "finance": True, "news": True}
    assert s["photo_card"] is True and s["news_count"] == 5


def test_merge_stored_overrides_and_fills_new_keys():
    s = merge({"briefing_time": "08:00", "sections": {"news": False}}, "07:00")
    assert s["briefing_time"] == "08:00"
    assert s["sections"]["news"] is False and s["sections"]["weather"] is True
    assert s["news_count"] == 5


def test_validate_ok():
    s = validate({**DEFAULTS, "briefing_time": "6:05", "news_count": 3})
    assert s["briefing_time"] == "06:05" and s["news_count"] == 3


@pytest.mark.parametrize("patch", [
    {"briefing_time": "25:00"},
    {"briefing_time": "07:60"},
    {"briefing_time": "sabah"},
    {"news_count": 0},
    {"news_count": 11},
    {"news_count": "5"},
    {"photo_card": "evet"},
    {"sections": {"weather": True}},
    {"sections": {**DEFAULTS["sections"], "spor": True}},
    {"tema": "koyu"},
])
def test_validate_rejects(patch):
    with pytest.raises(SettingsError):
        validate({**DEFAULTS, **patch})


def test_validate_requires_one_section():
    with pytest.raises(SettingsError, match="en az bir"):
        validate({**DEFAULTS, "sections": {s: False for s in DEFAULTS["sections"]}})
