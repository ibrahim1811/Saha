from datetime import date

from app.calendar_tr import holiday_on, school_line, upcoming, yks_line


def test_holiday_on():
    assert holiday_on(date(2026, 11, 18)) == "1. dönem ara tatili"
    assert holiday_on(date(2027, 1, 30)) == "Yarıyıl tatili"
    assert holiday_on(date(2026, 11, 23)) is None


def test_upcoming_within_window():
    names = [e[2] for e in upcoming(date(2026, 11, 5), 14)]
    assert names == ["1. dönem ara tatili"]
    assert upcoming(date(2026, 10, 10), 14) == []


def test_yks_line():
    assert yks_line(date(2026, 10, 10), date(2027, 6, 19), True) == "🎯 YKS'ye 252 gün (tahmini 19 Haziran 2027)"
    assert yks_line(date(2027, 6, 19), date(2027, 6, 19), False) == "🎯 YKS bugün! Başarılar 🍀"
    assert yks_line(date(2027, 6, 25), date(2027, 6, 19), False) is None


def test_school_line_combines():
    text = school_line(date(2026, 11, 5), date(2027, 6, 19), True)
    assert text.startswith("🎯 YKS'ye") and "📅 1. dönem ara tatili 11 gün sonra (16 Kasım)" in text
    assert "🏖 Bugün 1. dönem ara tatili" in school_line(date(2026, 11, 17), date(2027, 6, 19), True)
