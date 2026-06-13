"""Format post summaries into readable Telegram digests."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.pipeline.types import PostSummary

_RU_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_html_attr(text: str) -> str:
    return _escape_html(text).replace('"', "&quot;")


def digest_target_date(timezone_name: str) -> date:
    """Calendar date the digest covers (yesterday in the configured timezone)."""
    tz = ZoneInfo(timezone_name)
    return (datetime.now(tz) + timedelta(days=-1)).date()


def format_digest_date(value: date) -> str:
    return f"{value.day} {_RU_MONTHS[value.month - 1]} {value.year}"


def _format_channel(channel: str) -> str:
    """Plain channel title without @username suffix."""
    channel = channel.strip()
    if not channel:
        return ""
    if "(@" in channel:
        channel = channel.rsplit(" (@", 1)[0].strip()
    channel = channel.lstrip("@")
    return _escape_html(channel)


def format_post_card(item: PostSummary) -> str:
    """Card: rank → title → channel → summary → link."""
    title = _escape_html(item.title)
    summary = _escape_html(item.summary)
    url = _escape_html_attr(item.url)
    rank = item.rank if item.rank > 0 else "—"
    channel_line = ""
    channel = _format_channel(item.channel)
    if channel:
        channel_line = f"📡 {channel}\n\n"
    return (
        f"🔹 <b>#{rank}</b> · <b>{title}</b>\n\n"
        f"{channel_line}"
        f"{summary}\n\n"
        f'<a href="{url}">Подробнее</a>'
    )


def format_category_digest(
    category: str,
    items: list[PostSummary],
) -> str:
    """One message per theme with top posts."""
    if not items:
        return ""
    parts: list[str] = [f"<b>{_escape_html(category)}</b>"]
    for item in sorted(items, key=lambda x: x.rank):
        parts.append(format_post_card(item))
    return "\n\n".join(parts).strip()


def format_digest_toc(
    digest_date: date,
    summaries_by_category: dict[str, list[PostSummary]],
) -> str:
    """Table of contents for expandable digest."""
    categories = [c for c in sorted(summaries_by_category) if summaries_by_category[c]]
    if not categories:
        return "За вчера новых постов не найдено."

    total_posts = sum(len(summaries_by_category[c]) for c in categories)
    lines = [
        f"<b>Дайджест за {format_digest_date(digest_date)}</b>",
        f"{len(categories)} тем · {total_posts} постов",
        "",
        "Нажмите тему, чтобы развернуть:",
    ]
    return "\n".join(lines)


def format_digest_markdown(summaries_by_category: dict[str, list[PostSummary]]) -> str:
    """Legacy: single combined digest (used by CLI preview)."""
    if not summaries_by_category:
        return "За вчера новых постов не найдено."

    parts: list[str] = ["<b>Ежедневный Telegram-дайджест</b>"]
    for category in sorted(summaries_by_category):
        items = summaries_by_category[category]
        if not items:
            continue
        parts.append(f"\n<b>{_escape_html(category)}</b>")
        for item in sorted(items, key=lambda x: x.rank):
            parts.append("\n" + format_post_card(item))
    return "\n".join(parts).strip()
