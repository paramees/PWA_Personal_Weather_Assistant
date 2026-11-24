from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import aiosqlite

from weather_wardrobe.models import (
    DaySchedule,
    UserProfile,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    city_name TEXT,
    latitude REAL,
    longitude REAL,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    active_start_hour INTEGER NOT NULL DEFAULT 8,
    active_end_hour INTEGER NOT NULL DEFAULT 21,
    comfort_offset INTEGER NOT NULL DEFAULT 0,
    wardrobe_text TEXT NOT NULL DEFAULT '',
    use_ai INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedules (
    user_id INTEGER NOT NULL,
    weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
    enabled INTEGER NOT NULL DEFAULT 0,
    send_time TEXT NOT NULL DEFAULT '08:00',
    PRIMARY KEY (user_id, weekday),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedback_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    local_date TEXT NOT NULL,
    feeling TEXT NOT NULL CHECK(feeling IN ('cold', 'ok', 'hot')),
    feels_avg REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS delivery_logs (
    user_id INTEGER NOT NULL,
    local_date TEXT NOT NULL,
    schedule_time TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (user_id, local_date, schedule_time),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
"""


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _clamp_comfort(value: int) -> int:
    return max(-5, min(5, value))


def _row_to_user(row: aiosqlite.Row) -> UserProfile:
    return UserProfile(
        user_id=row["user_id"],
        city_name=row["city_name"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        timezone=row["timezone"],
        active_start_hour=row["active_start_hour"],
        active_end_hour=row["active_end_hour"],
        comfort_offset=row["comfort_offset"],
        wardrobe_text=row["wardrobe_text"],
        use_ai=bool(row["use_ai"]),
    )


def _row_to_schedule(row: aiosqlite.Row) -> DaySchedule:
    return DaySchedule(
        weekday=row["weekday"],
        enabled=bool(row["enabled"]),
        send_time=row["send_time"],
    )


class Repository:
    """Async SQLite repository for users, per-day schedules, feedback, and deliveries."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        """Open SQLite connection, enable WAL & foreign keys, and ensure schema."""
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()
        self._conn = conn

    async def close(self) -> None:
        """Close the underlying SQLite connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Repository is not initialized. Call await repo.init() first.")
        return self._conn

    async def _ensure_user_locked(self, user_id: int) -> None:
        now = _utc_now_iso()
        await self.conn.execute(
            """
            INSERT OR IGNORE INTO users (user_id, created_at, updated_at)
            VALUES (?, ?, ?)
            """,
            (user_id, now, now),
        )
        for weekday in range(7):
            await self.conn.execute(
                """
                INSERT OR IGNORE INTO schedules (user_id, weekday, enabled, send_time)
                VALUES (?, ?, 0, '08:00')
                """,
                (user_id, weekday),
            )

    async def get_or_create_user(self, user_id: int) -> UserProfile:
        """Fetch an existing user profile or create one with default 7-day schedules."""
        async with self._lock:
            await self._ensure_user_locked(user_id)
            await self.conn.commit()
            cursor = await self.conn.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            assert row is not None
            return _row_to_user(row)

    async def get_user(self, user_id: int) -> UserProfile | None:
        """Fetch user profile or return None if not registered."""
        cursor = await self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return _row_to_user(row) if row is not None else None

    async def update_location(
        self,
        user_id: int,
        city_name: str,
        latitude: float,
        longitude: float,
        timezone: str,
    ) -> None:
        async with self._lock:
            await self._ensure_user_locked(user_id)
            await self.conn.execute(
                """
                UPDATE users
                SET city_name = ?, latitude = ?, longitude = ?, timezone = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (city_name, latitude, longitude, timezone, _utc_now_iso(), user_id),
            )
            await self.conn.commit()

    async def update_active_hours(self, user_id: int, start_hour: int, end_hour: int) -> None:
        if not (0 <= start_hour < end_hour <= 23):
            raise ValueError("start_hour must be less than end_hour within 0..23")
        async with self._lock:
            await self._ensure_user_locked(user_id)
            await self.conn.execute(
                """
                UPDATE users
                SET active_start_hour = ?, active_end_hour = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (start_hour, end_hour, _utc_now_iso(), user_id),
            )
            await self.conn.commit()

    async def update_comfort_offset(self, user_id: int, offset: int) -> int:
        clamped = _clamp_comfort(offset)
        async with self._lock:
            await self._ensure_user_locked(user_id)
            await self.conn.execute(
                """
                UPDATE users
                SET comfort_offset = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (clamped, _utc_now_iso(), user_id),
            )
            await self.conn.commit()
        return clamped

    async def adjust_comfort_offset(self, user_id: int, delta: int) -> int:
        async with self._lock:
            await self._ensure_user_locked(user_id)
            cursor = await self.conn.execute(
                "SELECT comfort_offset FROM users WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            current = int(row["comfort_offset"]) if row is not None else 0
            updated = _clamp_comfort(current + delta)
            await self.conn.execute(
                """
                UPDATE users
                SET comfort_offset = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (updated, _utc_now_iso(), user_id),
            )
            await self.conn.commit()
            return updated

    async def update_wardrobe(self, user_id: int, wardrobe_text: str) -> None:
        async with self._lock:
            await self._ensure_user_locked(user_id)
            await self.conn.execute(
                """
                UPDATE users
                SET wardrobe_text = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (wardrobe_text.strip(), _utc_now_iso(), user_id),
            )
            await self.conn.commit()

    async def set_use_ai(self, user_id: int, use_ai: bool) -> None:
        async with self._lock:
            await self._ensure_user_locked(user_id)
            await self.conn.execute(
                """
                UPDATE users
                SET use_ai = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (int(use_ai), _utc_now_iso(), user_id),
            )
            await self.conn.commit()

    async def get_schedules(self, user_id: int) -> list[DaySchedule]:
        """Return all 7 weekday schedules (0=Monday..6=Sunday)."""
        async with self._lock:
            await self._ensure_user_locked(user_id)
            await self.conn.commit()
            cursor = await self.conn.execute(
                """
                SELECT weekday, enabled, send_time
                FROM schedules
                WHERE user_id = ?
                ORDER BY weekday ASC
                """,
                (user_id,),
            )
            rows = await cursor.fetchall()
            return [_row_to_schedule(row) for row in rows]

    async def set_day_schedule(
        self,
        user_id: int,
        weekday: int,
        enabled: bool,
        send_time: str,
    ) -> None:
        if not 0 <= weekday <= 6:
            raise ValueError("weekday must be in 0..6")
        async with self._lock:
            await self._ensure_user_locked(user_id)
            await self.conn.execute(
                """
                INSERT INTO schedules (user_id, weekday, enabled, send_time)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, weekday)
                DO UPDATE SET enabled = excluded.enabled, send_time = excluded.send_time
                """,
                (user_id, weekday, int(enabled), send_time),
            )
            await self.conn.commit()

    async def toggle_day_schedule(self, user_id: int, weekday: int) -> DaySchedule:
        if not 0 <= weekday <= 6:
            raise ValueError("weekday must be in 0..6")
        async with self._lock:
            await self._ensure_user_locked(user_id)
            cursor = await self.conn.execute(
                """
                SELECT weekday, enabled, send_time
                FROM schedules
                WHERE user_id = ? AND weekday = ?
                """,
                (user_id, weekday),
            )
            row = await cursor.fetchone()
            assert row is not None
            new_enabled = not bool(row["enabled"])
            await self.conn.execute(
                "UPDATE schedules SET enabled = ? WHERE user_id = ? AND weekday = ?",
                (int(new_enabled), user_id, weekday),
            )
            await self.conn.commit()
            return DaySchedule(weekday=weekday, enabled=new_enabled, send_time=row["send_time"])

    async def apply_time_to_enabled_days(self, user_id: int, send_time: str) -> None:
        async with self._lock:
            await self._ensure_user_locked(user_id)
            await self.conn.execute(
                """
                UPDATE schedules
                SET send_time = ?
                WHERE user_id = ? AND enabled = 1
                """,
                (send_time, user_id),
            )
            await self.conn.commit()

    async def apply_schedule_preset(
        self,
        user_id: int,
        preset: Literal["weekdays_0730", "all_0800", "off_all"],
    ) -> None:
        async with self._lock:
            await self._ensure_user_locked(user_id)
            for weekday in range(7):
                if preset == "weekdays_0730":
                    enabled = 1 if weekday < 5 else 0
                    send_time = "07:30"
                    await self.conn.execute(
                        """
                        UPDATE schedules
                        SET enabled = ?, send_time = ?
                        WHERE user_id = ? AND weekday = ?
                        """,
                        (enabled, send_time, user_id, weekday),
                    )
                elif preset == "all_0800":
                    await self.conn.execute(
                        """
                        UPDATE schedules
                        SET enabled = 1, send_time = '08:00'
                        WHERE user_id = ? AND weekday = ?
                        """,
                        (user_id, weekday),
                    )
                elif preset == "off_all":
                    await self.conn.execute(
                        "UPDATE schedules SET enabled = 0 WHERE user_id = ? AND weekday = ?",
                        (user_id, weekday),
                    )
            await self.conn.commit()

    async def get_all_enabled_schedules(self) -> list[tuple[UserProfile, DaySchedule]]:
        """Return enabled schedule entries for users who have a configured location."""
        cursor = await self.conn.execute(
            """
            SELECT u.*, s.weekday, s.enabled, s.send_time
            FROM schedules s
            JOIN users u ON u.user_id = s.user_id
            WHERE s.enabled = 1
              AND u.latitude IS NOT NULL
              AND u.longitude IS NOT NULL
            ORDER BY u.user_id, s.weekday
            """
        )
        rows = await cursor.fetchall()
        return [(_row_to_user(row), _row_to_schedule(row)) for row in rows]

    async def try_mark_delivered(
        self,
        user_id: int,
        local_date: str,
        schedule_time: str,
    ) -> bool:
        """Atomically record delivery; returns False if already sent for this date & time."""
        async with self._lock:
            cursor = await self.conn.execute(
                """
                INSERT OR IGNORE INTO delivery_logs (user_id, local_date, schedule_time, sent_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, local_date, schedule_time, _utc_now_iso()),
            )
            await self.conn.commit()
            return cursor.rowcount == 1

    async def log_feedback(
        self,
        user_id: int,
        local_date: str,
        feeling: Literal["cold", "ok", "hot"],
        feels_avg: float | None = None,
    ) -> None:
        async with self._lock:
            await self._ensure_user_locked(user_id)
            await self.conn.execute(
                """
                INSERT INTO feedback_logs (user_id, local_date, feeling, feels_avg, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, local_date, feeling, feels_avg, _utc_now_iso()),
            )
            await self.conn.commit()

    async def get_recent_feedback(self, user_id: int, limit: int = 5) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            """
            SELECT local_date, feeling, feels_avg, created_at
            FROM feedback_logs
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
