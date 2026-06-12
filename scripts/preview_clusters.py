"""Print cluster distribution from channels.csv (no Telegram API)."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from app.channels.cluster import infer_theme_cluster
from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    path = Path(settings.channels_csv_path)
    if not path.is_file():
        print(f"File not found: {path}. Run: make export-channels")
        return

    by_theme: Counter[str] = Counter()
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            theme = infer_theme_cluster(row.get("title", ""), row.get("about", ""))
            by_theme[theme] += 1

    print(f"Channels: {sum(by_theme.values())}\n")
    for theme, count in by_theme.most_common():
        print(f"  {count:3d}  {theme}")


if __name__ == "__main__":
    main()
