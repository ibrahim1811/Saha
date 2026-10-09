from datetime import date

MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
EVENTS = [
    (date(2026, 9, 14), date(2026, 9, 14), "1. dönem başlangıcı"),
    (date(2026, 11, 16), date(2026, 11, 20), "1. dönem ara tatili"),
    (date(2027, 1, 22), date(2027, 1, 22), "Karne günü"),
    (date(2027, 1, 25), date(2027, 2, 5), "Yarıyıl tatili"),
    (date(2027, 2, 8), date(2027, 2, 8), "2. dönem başlangıcı"),
    (date(2027, 3, 8), date(2027, 3, 12), "2. dönem ara tatili"),
    (date(2027, 6, 25), date(2027, 6, 25), "Yıl sonu, karne günü"),
]
HOLIDAYS = {"1. dönem ara tatili", "Yarıyıl tatili", "2. dönem ara tatili"}


def fmt_day(d: date, year: bool = False) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}" + (f" {d.year}" if year else "")


def holiday_on(d: date) -> str | None:
    for start, end, name in EVENTS:
        if name in HOLIDAYS and start <= d <= end:
            return name
    return None


def upcoming(d: date, within: int = 14) -> list[tuple[date, date, str]]:
    return [e for e in EVENTS if 0 < (e[0] - d).days <= within]


def yks_line(d: date, yks: date, estimated: bool) -> str | None:
    days = (yks - d).days
    if days < 0:
        return None
    if days == 0:
        return "🎯 YKS bugün! Başarılar 🍀"
    note = f"tahmini {fmt_day(yks, True)}" if estimated else fmt_day(yks, True)
    return f"🎯 YKS'ye {days} gün ({note})"


def school_line(d: date, yks: date, estimated: bool) -> str:
    lines = [line for line in [yks_line(d, yks, estimated)] if line]
    today_holiday = holiday_on(d)
    if today_holiday:
        lines.append(f"🏖 Bugün {today_holiday}")
    for start, _, name in upcoming(d):
        lines.append(f"📅 {name} {(start - d).days} gün sonra ({fmt_day(start)})")
    return "\n".join(lines) or "Yaklaşan bir okul olayı yok."
