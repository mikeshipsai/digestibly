"""Project configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

MAX_MESSAGES_PER_CHANNEL: int = 50


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Environment variable {name} is required")
    return value


def _require_int_env(name: str) -> int:
    return int(_require_env(name))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_phone: str
    telegram_password: str
    owner_chat_id: int
    bot_token: str
    gemini_api_key: str
    digest_hour: int
    digest_minute: int
    timezone: str
    debug_collect_only: bool
    sqlite_path: str
    telethon_session_name: str
    channels_csv_path: str
    digest_top_n: int
    batch_hour: int
    batch_minute: int
    min_posts_per_theme: int
    gemini_rpm: int
    groq_api_key: str
    groq_model: str
    groq_rpm: int
    ai_cluster_enabled: bool


def get_settings() -> Settings:
    owner_raw = os.getenv("OWNER_CHAT_ID") or os.getenv("ADMIN_CHAT_ID") or ""
    if not owner_raw.strip():
        raise ValueError("OWNER_CHAT_ID (or ADMIN_CHAT_ID) is required")

    return Settings(
        telegram_api_id=_require_int_env("TELEGRAM_API_ID"),
        telegram_api_hash=_require_env("TELEGRAM_API_HASH"),
        telegram_phone=_require_env("TELEGRAM_PHONE"),
        telegram_password=(os.getenv("TELEGRAM_PASSWORD") or os.getenv("TELEGRAM_2FA_PASSWORD") or "").strip(),
        owner_chat_id=int(owner_raw.strip()),
        bot_token=_require_env("BOT_TOKEN"),
        gemini_api_key=_require_env("GEMINI_API_KEY"),
        digest_hour=int(os.getenv("DIGEST_HOUR", "9")),
        digest_minute=int(os.getenv("DIGEST_MINUTE", "0")),
        timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
        debug_collect_only=_env_bool("DEBUG_COLLECT_ONLY", False),
        sqlite_path=os.getenv("SQLITE_PATH", "data/debug_posts.sqlite3").strip() or "data/debug_posts.sqlite3",
        telethon_session_name=os.getenv("TELETHON_SESSION_NAME", "data/telegram_digest_userbot").strip()
        or "data/telegram_digest_userbot",
        channels_csv_path=os.getenv("CHANNELS_CSV_PATH", "data/channels.csv").strip() or "data/channels.csv",
        digest_top_n=int(os.getenv("DIGEST_TOP_N", "5")),
        batch_hour=int(os.getenv("BATCH_HOUR", "4")),
        batch_minute=int(os.getenv("BATCH_MINUTE", "0")),
        min_posts_per_theme=int(os.getenv("MIN_POSTS_PER_THEME", "3")),
        gemini_rpm=int(os.getenv("GEMINI_RPM", "4")),
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_model=os.getenv("GROQ_MODEL", "qwen/qwen3-32b").strip() or "qwen/qwen3-32b",
        groq_rpm=int(os.getenv("GROQ_RPM", "30")),
        ai_cluster_enabled=_env_bool("AI_CLUSTER_ENABLED", True),
    )
