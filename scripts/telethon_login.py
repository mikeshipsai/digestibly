"""One-time interactive Telethon login to create session file."""

from __future__ import annotations

import asyncio

from telethon import TelegramClient

from app.core.config import get_settings


async def _login() -> None:
    settings = get_settings()
    client = TelegramClient(
        settings.telethon_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
    await client.start(
        phone=settings.telegram_phone,
        password=settings.telegram_password or None,
    )
    me = await client.get_me()
    print(f"Telethon session authorized for user id={me.id}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(_login())
