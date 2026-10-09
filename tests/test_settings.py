import pytest

from app.settings import DEFAULTS, SettingsError, merge, validate


def test_merge_defaults_with_env_time():
    s = merge(None, "06:30")
    assert s["briefing_time"] == "06:30"
    assert s["sections"] == {"school": True, "weather": True, "lessons": True, "tasks": True, "finance": True, "news": True}
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


def test_evening_defaults_and_tasks_section():
    s = merge({"sections": {"news": False}}, "07:00")
    assert s["evening_enabled"] is True and s["evening_time"] == "23:00"
    assert s["sections"]["tasks"] is True


@pytest.mark.parametrize("patch", [{"evening_time": "24:00"}, {"evening_enabled": "evet"}])
def test_evening_validation(patch):
    with pytest.raises(SettingsError):
        validate({**DEFAULTS, **patch})


def test_evening_time_normalized():
    assert validate({**DEFAULTS, "evening_time": "9:05"})["evening_time"] == "09:05"


def test_evening_needs_an_evening_section():
    only_market = {**DEFAULTS["sections"], "weather": False, "lessons": False, "tasks": False}
    with pytest.raises(SettingsError, match="Akşam"):
        validate({**DEFAULTS, "sections": only_market})
    assert validate({**DEFAULTS, "sections": only_market, "evening_enabled": False})["evening_enabled"] is False


def test_school_defaults():
    s = merge(None, "07:00")
    assert s["sections"]["school"] is True and s["weather_alerts"] is True
    assert s["yks_date"] == "2027-06-19" and s["yks_estimated"] is True
    assert s["target_tyt"] is None and s["target_ayt"] is None


def test_school_settings_valid():
    out = validate({**DEFAULTS, "yks_date": "2027-06-12", "yks_estimated": False, "target_tyt": 95, "target_ayt": 60.5})
    assert out["yks_date"] == "2027-06-12" and out["target_tyt"] == 95 and out["target_ayt"] == 60.5


@pytest.mark.parametrize("patch", [
    {"yks_date": "19.06.2027"}, {"yks_estimated": "evet"}, {"target_tyt": 130}, {"target_ayt": 81},
    {"target_tyt": "90"}, {"weather_alerts": 1},
])
def test_school_settings_invalid(patch):
    with pytest.raises(SettingsError):
        validate({**DEFAULTS, **patch})
