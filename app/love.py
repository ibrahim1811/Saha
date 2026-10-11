from datetime import date

from app.settings import SettingsError

ALERT_DAYS_BEFORE = 3
SOON_DAYS = 7


def _on_year(day: date, year: int) -> date:
    try:
        return day.replace(year=year)
    except ValueError:
        return day.replace(year=year, day=28)


def next_occurrence(row: dict, today: date) -> date | None:
    day = row["day"]
    if not row["yearly"]:
        return day if day >= today else None
    this_year = _on_year(day, today.year)
    return this_year if this_year >= today else _on_year(day, today.year + 1)


def lines(rows: list[dict], today: date) -> list[str]:
    out = []
    for row in rows:
        if row["counter"] and row["day"] <= today:
            out.append(f"❤️ {row['name']}: {(today - row['day']).days + 1}. gün")
        nxt = next_occurrence(row, today)
        if nxt is None or nxt == row["day"] and row["counter"]:
            continue
        left = (nxt - today).days
        years = nxt.year - row["day"].year
        suffix = f" ({years}. yıl)" if row["yearly"] and years > 0 else ""
        if left == 0:
            out.append(f"🎉 Bugün {row['name']}!{suffix}")
        elif left <= SOON_DAYS:
            out.append(f"📅 {row['name']}{suffix}: {left} gün kaldı")
    return out


def owner_alerts(rows: list[dict], today: date) -> list[str]:
    return [
        f"⏳ {ALERT_DAYS_BEFORE} gün sonra {row['name']}! ({nxt:%d.%m}) Hazırlığını yaptın mı? 🎁"
        for row in rows
        if (nxt := next_occurrence(row, today)) and (nxt - today).days == ALERT_DAYS_BEFORE
    ]


def validate_day(payload) -> dict:
    if not isinstance(payload, dict):
        raise SettingsError("Geçersiz istek")
    name = str(payload.get("name", "")).strip()
    if not name or len(name) > 60:
        raise SettingsError("Gün adı 1-60 karakter olmalı")
    try:
        day = date.fromisoformat(str(payload.get("day")))
    except ValueError as e:
        raise SettingsError("Tarih YYYY-AA-GG biçiminde olmalı") from e
    return {"name": name, "day": day, "yearly": payload.get("yearly") is True, "counter": payload.get("counter") is True}


def validate_note(payload) -> str:
    text = str((payload or {}).get("text", "")).strip() if isinstance(payload, dict) else ""
    if not text or len(text) > 1000:
        raise SettingsError("Not 1-1000 karakter olmalı")
    return text
