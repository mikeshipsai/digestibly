"""Telegram channel message collector (Telethon userbot)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from telethon import TelegramClient, utils
from telethon.errors import ChannelInvalidError, UsernameInvalidError, UsernameNotOccupiedError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Channel

from app.channels.ai_cluster import PROFILE_POSTS_LIMIT, classify_new_channels_by_posts
from app.channels.cluster import infer_theme_cluster
from app.channels.macro_themes import to_macro_theme
from app.channels.resolve import resolve_channel_theme
from app.channels.preprocess import preprocess_post
from app.core.config import MAX_MESSAGES_PER_CHANNEL, get_settings
from app.storage.posts import calendar_day_window
from app.storage.themes import (
    is_channel_muted,
    load_known_channel_keys,
    normalize_channel_key,
    register_known_channel,
)
from app.telegram.userbot import connect_ephemeral, run_exclusive

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BroadcastChannelInfo:
    title: str
    username: str | None
    channel_id: int
    about: str
    participants_count: int | None
    theme_cluster: str


def _is_broadcast_channel(entity: object) -> bool:
    return isinstance(entity, Channel) and bool(entity.broadcast) and not bool(entity.megagroup)


def _category_label_for_entity(entity: object) -> str:
    title = getattr(entity, "title", None)
    un = getattr(entity, "username", None)
    base = str(title).strip() if title else ""
    if base and un:
        return f"{base[:160]} (@{un})"[:200]
    if base:
        return base[:200]
    if un:
        return f"@{un}"
    return "Канал"


def _message_url(entity: object | None, message_id: int, channel_fallback: str) -> str:
    if entity is not None:
        username = getattr(entity, "username", None)
        if username:
            return f"https://t.me/{username}/{message_id}"
        try:
            peer_id = int(utils.get_peer_id(entity))
        except (TypeError, ValueError):
            peer_id = 0
        if peer_id:
            inner = str(abs(peer_id))
            if inner.startswith("100"):
                inner = inner[3:]
            return f"https://t.me/c/{inner}/{message_id}"
    uname = channel_fallback.lstrip("@").split("/")[0]
    return f"https://t.me/{uname}/{message_id}"


def _engagement_counts(message: Any) -> tuple[int, int, int]:
    views = int(getattr(message, "views", 0) or 0)
    reactions = 0
    msg_reactions = getattr(message, "reactions", None)
    if msg_reactions is not None:
        for item in getattr(msg_reactions, "results", []) or []:
            reactions += int(getattr(item, "count", 0) or 0)
    replies = 0
    msg_replies = getattr(message, "replies", None)
    if msg_replies is not None:
        replies = int(getattr(msg_replies, "replies", 0) or 0)
    return views, reactions, replies


def _append_message_if_in_window(
    messages_out: list[dict[str, Any]],
    *,
    channel_label: str,
    channel_username: str | None,
    message: Any,
    since_dt: datetime,
    until_dt: datetime | None,
    entity_for_link: object | None,
    url_fallback: str,
) -> bool:
    if message.date is None:
        return False

    message_date = message.date
    if message_date.tzinfo is None:
        message_date = message_date.replace(tzinfo=timezone.utc)

    if message_date < since_dt:
        return False
    if until_dt is not None and message_date >= until_dt:
        return False

    raw_text = (message.text or "").strip()
    if not raw_text:
        return False

    pre = preprocess_post(raw_text)
    if not pre.text_clean:
        return False

    views, reactions, replies = _engagement_counts(message)
    messages_out.append(
        {
            "channel": channel_label,
            "channel_username": channel_username or "",
            "text": pre.text_clean,
            "tags": list(pre.tags),
            "mentions": list(pre.mentions),
            "date": message_date,
            "url": _message_url(entity_for_link, message.id, url_fallback),
            "views": views,
            "reactions": reactions,
            "replies": replies,
        }
    )
    return True


async def _iter_broadcast_entities(client: TelegramClient):
    for dialog in await client.get_dialogs():
        entity = dialog.entity
        if _is_broadcast_channel(entity):
            yield entity


async def _fetch_profile_posts(client: TelegramClient, entity: object) -> list[str]:
    posts: list[str] = []
    try:
        async for message in client.iter_messages(entity, limit=PROFILE_POSTS_LIMIT):
            raw = (message.text or "").strip()
            if raw:
                posts.append(raw)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Profile posts fetch failed: %s", exc)
    return posts


async def _collect_with_client(
    client: TelegramClient,
    *,
    since_dt: datetime,
    until_dt: datetime,
) -> dict[str, list[dict[str, Any]]]:
    settings = get_settings()
    result: dict[str, list[dict[str, Any]]] = {}
    entities: list[object] = []
    channel_meta: list[dict] = []

    async for entity in _iter_broadcast_entities(client):
        entities.append(entity)
        title = str(getattr(entity, "title", "") or "Канал").strip()
        username = getattr(entity, "username", None)
        about = ""
        try:
            full = await client(GetFullChannelRequest(entity))
            about = (full.full_chat.about or "").strip()
        except Exception:  # noqa: BLE001
            pass
        channel_meta.append({"title": title, "username": username, "about": about})

    logger.info("Found %s broadcast channels", len(entities))

    known_keys = load_known_channel_keys()
    new_count = 0
    for entity, meta in zip(entities, channel_meta, strict=True):
        title = meta["title"]
        username = meta.get("username")
        channel_key = normalize_channel_key(username, title)
        if is_channel_muted(channel_key):
            logger.info("Skipping muted channel: %s", channel_key)
            continue
        if channel_key not in known_keys:
            new_count += 1
        meta["entity"] = entity
        register_known_channel(
            channel_key,
            channel_id=int(getattr(entity, "id", 0) or 0) or None,
            title=title,
        )

    if new_count:
        logger.info("Detected %s new channels", new_count)

    classifiable_meta = [
        meta
        for meta in channel_meta
        if not is_channel_muted(normalize_channel_key(meta.get("username"), meta["title"]))
    ]
    try:
        await classify_new_channels_by_posts(
            classifiable_meta,
            posts_fetcher=lambda entity: _fetch_profile_posts(client, entity),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Post-based channel classification skipped: %s", exc)

    for entity, meta in zip(entities, channel_meta, strict=True):
        title = meta["title"]
        username = meta.get("username")
        about = meta.get("about", "")
        channel_key = normalize_channel_key(username, title)
        if is_channel_muted(channel_key):
            continue
        theme = resolve_channel_theme(title, about, username=username)
        await _collect_channel_posts(
            client,
            entity=entity,
            category=theme,
            since_dt=since_dt,
            until_dt=until_dt,
            result=result,
        )
    return result


async def _collect_channel_posts(
    client: TelegramClient,
    *,
    entity: object,
    category: str,
    since_dt: datetime,
    until_dt: datetime | None,
    result: dict[str, list[dict[str, Any]]],
) -> None:
    if category not in result:
        result[category] = []
    ch_label = _category_label_for_entity(entity)
    un = getattr(entity, "username", None)
    url_fb = f"@{un}" if un else ch_label
    count = 0
    try:
        async for message in client.iter_messages(entity, limit=MAX_MESSAGES_PER_CHANNEL):
            added = _append_message_if_in_window(
                result[category],
                channel_label=ch_label,
                channel_username=str(un) if un else None,
                message=message,
                since_dt=since_dt,
                until_dt=until_dt,
                entity_for_link=entity,
                url_fallback=url_fb,
            )
            if not added and message.date is not None:
                md = message.date
                if md.tzinfo is None:
                    md = md.replace(tzinfo=timezone.utc)
                if md < since_dt:
                    break
            if added:
                count += 1
    except (UsernameInvalidError, UsernameNotOccupiedError, ChannelInvalidError, ValueError):
        logger.warning("Channel not found or unavailable: %s", ch_label)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed collecting from channel %s: %s", ch_label, exc)
    else:
        logger.info("Collected %s messages from %s [%s]", count, ch_label, category)


async def list_broadcast_channels(*, standalone: bool = True) -> list[BroadcastChannelInfo]:
    """List broadcast channels with description and theme (for CSV export)."""
    channels: list[BroadcastChannelInfo] = []

    async def _list(client: TelegramClient) -> list[BroadcastChannelInfo]:
        out: list[BroadcastChannelInfo] = []
        async for entity in _iter_broadcast_entities(client):
            title = str(getattr(entity, "title", "") or "Канал").strip()
            username = getattr(entity, "username", None)
            about = ""
            participants_count: int | None = None
            try:
                full = await client(GetFullChannelRequest(entity))
                about = (full.full_chat.about or "").strip()
                participants_count = getattr(full.full_chat, "participants_count", None)
            except Exception as exc:  # noqa: BLE001
                logger.debug("GetFullChannel failed for %s: %s", title, exc)
            out.append(
                BroadcastChannelInfo(
                    title=title,
                    username=str(username) if username else None,
                    channel_id=int(entity.id),
                    about=about,
                    participants_count=participants_count,
                    theme_cluster=to_macro_theme(infer_theme_cluster(title, about)),
                )
            )
        return out

    if standalone:
        client = await connect_ephemeral()
        try:
            channels = await _list(client)
        finally:
            await client.disconnect()
    else:
        channels = await run_exclusive(_list)

    channels.sort(key=lambda c: (c.theme_cluster, c.title.lower()))
    return channels


async def collect_messages_for_category(
    category: str,
    usernames: set[str],
    *,
    standalone: bool = False,
) -> list[dict[str, Any]]:
    """Collect yesterday's posts from channels whose username is in usernames."""
    settings = get_settings()
    since_dt, until_dt = calendar_day_window(settings.timezone, day_offset=-1)
    normalized = {u.lower().lstrip("@") for u in usernames}

    async def _collect(client: TelegramClient) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        bucket: dict[str, list[dict[str, Any]]] = {category: messages}
        matched = 0
        async for entity in _iter_broadcast_entities(client):
            if not _is_broadcast_channel(entity):
                continue
            username = str(getattr(entity, "username", "") or "").lower()
            if username not in normalized:
                continue
            matched += 1
            await _collect_channel_posts(
                client,
                entity=entity,
                category=category,
                since_dt=since_dt,
                until_dt=until_dt,
                result=bucket,
            )
        logger.info(
            "Category %s: matched %s/%s channels from filter",
            category,
            matched,
            len(normalized),
        )
        return messages

    if standalone:
        client = await connect_ephemeral()
        try:
            return await _collect(client)
        finally:
            await client.disconnect()

    return await run_exclusive(_collect)


async def collect_messages(*, standalone: bool = False) -> dict[str, list[dict[str, Any]]]:
    """Collect yesterday's posts from all broadcast channels, grouped by theme."""
    settings = get_settings()
    since_dt, until_dt = calendar_day_window(settings.timezone, day_offset=-1)
    logger.info("Collecting calendar yesterday: %s — %s UTC", since_dt, until_dt)

    if standalone:
        client = await connect_ephemeral()
        try:
            logger.info("Collecting from all broadcast channels (standalone)")
            return await _collect_with_client(client, since_dt=since_dt, until_dt=until_dt)
        finally:
            await client.disconnect()

    logger.info("Collecting from all broadcast channels")
    return await run_exclusive(
        lambda client: _collect_with_client(client, since_dt=since_dt, until_dt=until_dt)
    )
