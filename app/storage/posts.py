"""SQLite storage for collected posts."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_CREATE_COLLECTED_POSTS = """
CREATE TABLE collected_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    channel TEXT NOT NULL,
    channel_username TEXT,
    post_date TEXT NOT NULL,
    url TEXT NOT NULL,
    text TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    reactions INTEGER NOT NULL DEFAULT 0,
    replies INTEGER NOT NULL DEFAULT 0,
    UNIQUE(url)
)
"""

_EXTRA_COLUMNS = (
    ("channel_username", "TEXT"),
    ("views", "INTEGER NOT NULL DEFAULT 0"),
    ("reactions", "INTEGER NOT NULL DEFAULT 0"),
    ("replies", "INTEGER NOT NULL DEFAULT 0"),
)


def _connect(sqlite_path: str) -> sqlite3.Connection:
    Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(sqlite_path)


def _existing_columns(conn: sqlite3.Connection) -> set[str]:
    return {col[1] for col in conn.execute("PRAGMA table_info(collected_posts)").fetchall()}


def _ensure_schema(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='collected_posts'"
    ).fetchone()
    if row is None:
        conn.execute(_CREATE_COLLECTED_POSTS)
        return

    existing = _existing_columns(conn)
    for name, col_type in _EXTRA_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE collected_posts ADD COLUMN {name} {col_type}")


def save_collected_posts(all_messages: dict[str, list[dict]], sqlite_path: str) -> int:
    inserted = 0
    conn = _connect(sqlite_path)
    try:
        _ensure_schema(conn)
        for category, messages in all_messages.items():
            for message in messages:
                post_date = message.get("date")
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO collected_posts (
                        category, channel, channel_username, post_date, url, text,
                        views, reactions, replies
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(category),
                        str(message.get("channel", "")),
                        str(message.get("channel_username", "") or ""),
                        post_date.isoformat() if hasattr(post_date, "isoformat") else "",
                        str(message.get("url", "")),
                        str(message.get("text", "")),
                        int(message.get("views", 0) or 0),
                        int(message.get("reactions", 0) or 0),
                        int(message.get("replies", 0) or 0),
                    ),
                )
                if cur.rowcount > 0:
                    inserted += 1
        conn.commit()
    finally:
        conn.close()
    return inserted


def load_posts_grouped(sqlite_path: str, *, run_id: int | None = None) -> dict[str, list[dict[str, Any]]]:
    """Load posts grouped by category."""
    conn = _connect(sqlite_path)
    try:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT category, channel, channel_username, post_date, url, text,
                   views, reactions, replies
            FROM collected_posts
            ORDER BY category, post_date DESC
            """
        ).fetchall()
    finally:
        conn.close()

    result: dict[str, list[dict[str, Any]]] = {}
    for category, channel, username, post_date, url, text, views, reactions, replies in rows:
        result.setdefault(str(category), []).append(
            {
                "category": str(category),
                "channel": str(channel),
                "channel_username": str(username or ""),
                "text": str(text),
                "tags": [],
                "mentions": [],
                "date": _parse_date(post_date),
                "url": str(url),
                "views": int(views or 0),
                "reactions": int(reactions or 0),
                "replies": int(replies or 0),
            }
        )
    return result


def delete_posts_older_than(sqlite_path: str, days: int = 2) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = _connect(sqlite_path)
    try:
        _ensure_schema(conn)
        cur = conn.execute("DELETE FROM collected_posts WHERE post_date < ?", (cutoff,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def calendar_day_window(timezone_name: str, *, day_offset: int = -1) -> tuple[datetime, datetime]:
    """Return UTC start/end for a calendar day in the given timezone."""
    tz = ZoneInfo(timezone_name)
    local_now = datetime.now(tz)
    target = (local_now + timedelta(days=day_offset)).date()
    start_local = datetime(target.year, target.month, target.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _parse_date(value: str) -> Any:
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.now(timezone.utc)


def count_posts(sqlite_path: str) -> int:
    conn = _connect(sqlite_path)
    try:
        _ensure_schema(conn)
        row = conn.execute("SELECT COUNT(*) FROM collected_posts").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()
