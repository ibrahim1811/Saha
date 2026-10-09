import json
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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


def clean_dsn(url: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "channel_binding"]
    return urlunsplit(parts._replace(query=urlencode(query)))


class DB:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def connect(cls, url: str) -> "DB":
        pool = await asyncpg.create_pool(clean_dsn(url), min_size=1, max_size=5)
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
