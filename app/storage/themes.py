"""Custom themes and per-channel overrides."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.core.config import get_settings
from app.storage.posts import _connect

_CREATE_CUSTOM_THEMES = """
CREATE TABLE custom_themes (
    name TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
)
"""

_CREATE_CHANNEL_OVERRIDES = """
CREATE TABLE channel_overrides (
    channel_key TEXT PRIMARY KEY,
    theme TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_CREATE_CHANNEL_AI_THEMES = """
CREATE TABLE channel_ai_themes (
    channel_key TEXT PRIMARY KEY,
    theme TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_CREATE_KNOWN_CHANNELS = """
CREATE TABLE known_channels (
    channel_key TEXT PRIMARY KEY,
    channel_id INTEGER,
    title TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
)
"""

_CREATE_MUTED_CHANNELS = """
CREATE TABLE muted_channels (
    channel_key TEXT PRIMARY KEY,
    muted_at TEXT NOT NULL
)
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='custom_themes'"
    ).fetchone() is None:
        conn.execute(_CREATE_CUSTOM_THEMES)
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='channel_overrides'"
    ).fetchone() is None:
        conn.execute(_CREATE_CHANNEL_OVERRIDES)
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='channel_ai_themes'"
    ).fetchone() is None:
        conn.execute(_CREATE_CHANNEL_AI_THEMES)
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='known_channels'"
    ).fetchone() is None:
        conn.execute(_CREATE_KNOWN_CHANNELS)
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='muted_channels'"
    ).fetchone() is None:
        conn.execute(_CREATE_MUTED_CHANNELS)


def normalize_channel_key(username: str | None, title: str) -> str:
    if username:
        uname = username.lstrip("@").lower()
        return f"@{uname}"
    return title.strip().lower()


def create_theme(name: str) -> bool:
    name = name.strip()
    if not name:
        raise ValueError("Theme name cannot be empty")
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "INSERT OR IGNORE INTO custom_themes (name, created_at) VALUES (?, ?)",
            (name, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_custom_themes() -> list[str]:
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        rows = conn.execute("SELECT name FROM custom_themes ORDER BY name").fetchall()
        return [str(r[0]) for r in rows]
    finally:
        conn.close()


def set_channel_override(channel_key: str, theme: str) -> None:
    channel_key = channel_key.strip().lower()
    if channel_key and not channel_key.startswith("@") and " " not in channel_key:
        channel_key = f"@{channel_key.lstrip('@')}"
    theme = theme.strip()
    if not channel_key or not theme:
        raise ValueError("Channel and theme are required")
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO channel_overrides (channel_key, theme, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(channel_key) DO UPDATE SET
                theme = excluded.theme,
                updated_at = excluded.updated_at
            """,
            (channel_key, theme, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def list_channel_overrides() -> dict[str, str]:
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT channel_key, theme FROM channel_overrides ORDER BY theme, channel_key"
        ).fetchall()
        return {str(k): str(t) for k, t in rows}
    finally:
        conn.close()


def get_channel_override(channel_key: str) -> str | None:
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT theme FROM channel_overrides WHERE channel_key = ?",
            (channel_key.strip().lower(),),
        ).fetchone()
        return str(row[0]) if row else None
    finally:
        conn.close()


def get_ai_theme(channel_key: str) -> str | None:
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT theme FROM channel_ai_themes WHERE channel_key = ?",
            (channel_key.strip().lower(),),
        ).fetchone()
        return str(row[0]) if row else None
    finally:
        conn.close()


def save_ai_theme(channel_key: str, theme: str) -> None:
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO channel_ai_themes (channel_key, theme, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(channel_key) DO UPDATE SET
                theme = excluded.theme,
                updated_at = excluded.updated_at
            """,
            (channel_key.strip().lower(), theme.strip(), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def load_all_ai_themes() -> dict[str, str]:
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        rows = conn.execute("SELECT channel_key, theme FROM channel_ai_themes").fetchall()
        return {str(k): str(t) for k, t in rows}
    finally:
        conn.close()


def load_known_channel_keys() -> set[str]:
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        rows = conn.execute("SELECT channel_key FROM known_channels").fetchall()
        return {str(r[0]) for r in rows}
    finally:
        conn.close()


def register_known_channel(
    channel_key: str,
    *,
    channel_id: int | None = None,
    title: str = "",
) -> None:
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO known_channels (channel_key, channel_id, title, first_seen_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_key) DO UPDATE SET
                channel_id = COALESCE(excluded.channel_id, known_channels.channel_id),
                title = CASE WHEN excluded.title != '' THEN excluded.title ELSE known_channels.title END
            """,
            (
                channel_key.strip().lower(),
                channel_id,
                title.strip(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_muted_channels() -> set[str]:
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        rows = conn.execute("SELECT channel_key FROM muted_channels").fetchall()
        return {str(r[0]) for r in rows}
    finally:
        conn.close()


def mute_channel(channel_key: str) -> bool:
    channel_key = channel_key.strip().lower()
    if channel_key and not channel_key.startswith("@") and " " not in channel_key:
        channel_key = f"@{channel_key.lstrip('@')}"
    if not channel_key:
        raise ValueError("Укажите канал: /mute @channel")
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "INSERT OR IGNORE INTO muted_channels (channel_key, muted_at) VALUES (?, ?)",
            (channel_key, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def unmute_channel(channel_key: str) -> bool:
    channel_key = channel_key.strip().lower()
    if channel_key and not channel_key.startswith("@") and " " not in channel_key:
        channel_key = f"@{channel_key.lstrip('@')}"
    settings = get_settings()
    conn = _connect(settings.sqlite_path)
    try:
        _ensure_schema(conn)
        cur = conn.execute("DELETE FROM muted_channels WHERE channel_key = ?", (channel_key,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def is_channel_muted(channel_key: str) -> bool:
    return channel_key.strip().lower() in list_muted_channels()


def list_channels_by_theme(theme: str | None = None) -> dict[str, str]:
    """Return channel_key -> macro theme from AI cache."""
    from app.channels.macro_themes import to_macro_theme

    themes = load_all_ai_themes()
    if theme is None:
        return themes
    target = to_macro_theme(theme)
    return {k: v for k, v in themes.items() if to_macro_theme(v) == target}
