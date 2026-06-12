"""Shared Telethon userbot client (one session per process)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from telethon import TelegramClient

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_client: TelegramClient | None = None
_lock = asyncio.Lock()


def _build_client() -> TelegramClient:
    settings = get_settings()
    return TelegramClient(
        settings.telethon_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )


async def _ensure_connected() -> TelegramClient:
    global _client
    if _client is None:
        _client = _build_client()
    if not _client.is_connected():
        await _client.connect()
        if not await _client.is_user_authorized():
            await _client.disconnect()
            _client = None
            raise RuntimeError(
                "Telethon session is not authorized. Run: make login"
            )
        logger.info("Telethon userbot connected")
    return _client


async def start_userbot() -> TelegramClient:
    """Connect shared client at bot startup."""
    async with _lock:
        return await _ensure_connected()


async def stop_userbot() -> None:
    """Disconnect shared client on shutdown."""
    global _client
    async with _lock:
        if _client is not None:
            await _client.disconnect()
            _client = None
            logger.info("Telethon userbot disconnected")


async def run_exclusive(
    coro_factory: Callable[[TelegramClient], Awaitable],
):
    """Serialize operations that use the Telethon SQLite session."""
    async with _lock:
        client = await _ensure_connected()
        return await coro_factory(client)


async def connect_ephemeral() -> TelegramClient:
    """Standalone connect for one-off CLI scripts (stop the bot first)."""
    client = _build_client()
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError(
            "Telethon session is not authorized. Run: make login"
        )
    return client
