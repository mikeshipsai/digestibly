"""Persisted user settings (schedule times) in SQLite."""

from __future__ import annotations

import sqlite3

from app.core.config import get_settings
from app.storage.posts import _connect

_CREATE_USER_SETTINGS = """
CREATE TABLE user_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_SCHEDULE_KEYS = ("batch_hour", "batch_minute", "digest_hour", "digest_minute")
_ONBOARDING_KEY = "onboarding_complete"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='user_settings'"
    ).fetchone() is None:
        conn.execute(_CREATE_USER_SETTINGS)


def _get_raw(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM user_settings WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row else None


def get_schedule() -> dict[str, int]:
    """Return effective schedule: DB overrides fall back to .env defaults."""
    settings = get_settings()
    defaults = {
        "batch_hour": settings.batch_hour,
        "batch_minute": settings.batch_minute,
        "digest_hour": settings.digest_hour,
        "digest_minute": settings.digest_minute,
    }
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        result = dict(defaults)
        for key in _SCHEDULE_KEYS:
            raw = _get_raw(conn, key)
            if raw is not None:
                result[key] = int(raw)
        return result
    finally:
        conn.close()


def set_schedule_value(key: str, value: int) -> None:
    if key not in _SCHEDULE_KEYS:
        raise ValueError(f"Unknown schedule key: {key}")
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        conn.execute(
            "INSERT INTO user_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        conn.commit()
    finally:
        conn.close()


def is_onboarded() -> bool:
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        return _get_raw(conn, _ONBOARDING_KEY) == "1"
    finally:
        conn.close()


def set_onboarded(*, complete: bool = True) -> None:
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        conn.execute(
            "INSERT INTO user_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_ONBOARDING_KEY, "1" if complete else "0"),
        )
        conn.commit()
    finally:
        conn.close()


def set_schedule(
    *,
    batch_hour: int | None = None,
    batch_minute: int | None = None,
    digest_hour: int | None = None,
    digest_minute: int | None = None,
) -> dict[str, int]:
    updates = {
        "batch_hour": batch_hour,
        "batch_minute": batch_minute,
        "digest_hour": digest_hour,
        "digest_minute": digest_minute,
    }
    for key, value in updates.items():
        if value is not None:
            set_schedule_value(key, value)
    return get_schedule()
