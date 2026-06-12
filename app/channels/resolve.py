"""Resolve channel theme: override → AI cache → keywords."""

from __future__ import annotations

from app.channels.cluster import infer_theme_cluster
from app.channels.macro_themes import to_macro_theme
from app.storage.themes import get_ai_theme, get_channel_override, normalize_channel_key


def resolve_channel_theme(
    title: str,
    about: str = "",
    *,
    username: str | None = None,
) -> str:
    channel_key = normalize_channel_key(username, title)

    override = get_channel_override(channel_key)
    if override:
        return to_macro_theme(override)

    ai_theme = get_ai_theme(channel_key)
    if ai_theme:
        return to_macro_theme(ai_theme)

    return to_macro_theme(infer_theme_cluster(title, about))
