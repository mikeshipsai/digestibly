"""Export all broadcast channels to CSV with thematic clusters."""

from __future__ import annotations

import asyncio
import csv
import logging
import sys
from pathlib import Path

from app.core.config import get_settings
from app.telegram.collector import list_broadcast_channels

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def _channel_url(username: str | None, channel_id: int) -> str:
    if username:
        return f"https://t.me/{username}"
    return f"tg://channel?id={channel_id}"


async def main() -> None:
    settings = get_settings()
    out_path = Path(settings.channels_csv_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    channels = await list_broadcast_channels()
    if not channels:
        logger.warning("No broadcast channels found")
        sys.exit(1)

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "theme_cluster",
                "title",
                "username",
                "url",
                "channel_id",
                "participants_count",
                "about",
            ],
        )
        writer.writeheader()
        for ch in channels:
            writer.writerow(
                {
                    "theme_cluster": ch.theme_cluster,
                    "title": ch.title,
                    "username": ch.username or "",
                    "url": _channel_url(ch.username, ch.channel_id),
                    "channel_id": ch.channel_id,
                    "participants_count": ch.participants_count or "",
                    "about": ch.about.replace("\n", " ").strip(),
                }
            )

    by_theme: dict[str, int] = {}
    for ch in channels:
        by_theme[ch.theme_cluster] = by_theme.get(ch.theme_cluster, 0) + 1

    logger.info("Exported %s channels to %s", len(channels), out_path.resolve())
    for theme, count in sorted(by_theme.items(), key=lambda x: (-x[1], x[0])):
        logger.info("  %s: %s", theme, count)


if __name__ == "__main__":
    asyncio.run(main())
