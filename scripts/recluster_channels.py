"""Re-apply theme clustering to existing channels.csv (no Telegram API)."""

from __future__ import annotations

import csv
import logging
import sys
from collections import Counter
from pathlib import Path

from app.channels.cluster import infer_theme_cluster
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

_FIELDNAMES = [
    "theme_cluster",
    "title",
    "username",
    "url",
    "channel_id",
    "participants_count",
    "about",
]


def main() -> None:
    settings = get_settings()
    path = Path(settings.channels_csv_path)
    if not path.is_file():
        logger.error("CSV not found: %s. Run: make export-channels", path)
        sys.exit(1)

    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            title = row.get("title", "")
            about = row.get("about", "")
            row["theme_cluster"] = infer_theme_cluster(title, about)
            rows.append(row)

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(r["theme_cluster"] for r in rows)
    logger.info("Reclustered %s channels → %s", len(rows), path.resolve())
    for theme, count in counts.most_common():
        logger.info("  %3d  %s", count, theme)


if __name__ == "__main__":
    main()
