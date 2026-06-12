"""Merge small theme buckets into «Прочее»."""

from __future__ import annotations

from typing import Any

DEFAULT_MIN_POSTS = 3
OTHER_THEME = "Прочее"


def merge_small_themes(
    messages_by_category: dict[str, list[dict[str, Any]]],
    *,
    min_posts: int = DEFAULT_MIN_POSTS,
    other_theme: str = OTHER_THEME,
) -> dict[str, list[dict[str, Any]]]:
    """Move categories with fewer than min_posts into other_theme."""
    merged: dict[str, list[dict[str, Any]]] = {}
    overflow: list[dict[str, Any]] = []

    for category, messages in messages_by_category.items():
        if not messages:
            continue
        if category == other_theme or len(messages) >= min_posts:
            merged.setdefault(category, []).extend(messages)
        else:
            overflow.extend(messages)

    if overflow:
        merged.setdefault(other_theme, []).extend(overflow)

    return merged
