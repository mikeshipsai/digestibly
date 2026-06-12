"""Run full digest pipeline: collect → LLM → SQLite summaries → formatted output."""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.core.config import get_settings
from app.pipeline.digest import run_digest, run_morning_digest, run_night_batch
from app.pipeline.format import format_digest_markdown
from app.storage.summaries import load_post_summaries

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run digest pipeline")
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Skip Telethon collect; use posts already in SQLite",
    )
    parser.add_argument(
        "--no-send",
        action="store_true",
        help="Do not send digest to Telegram (print preview only)",
    )
    parser.add_argument(
        "--batch-only",
        action="store_true",
        help="Run night batch only (collect + summarize all posts)",
    )
    parser.add_argument(
        "--morning-only",
        action="store_true",
        help="Run morning digest only (top-5 from last batch)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if settings.debug_collect_only:
        logger.warning("DEBUG_COLLECT_ONLY=true in .env — LLM step will be skipped")

    if args.batch_only:
        run_id = await run_night_batch(collect=not args.from_db)
    elif args.morning_only:
        run_id = await run_morning_digest(send_telegram=not args.no_send)
    else:
        run_id = await run_digest(
            send_telegram=not args.no_send,
            collect=not args.from_db,
            force_full=True,
        )
    if run_id is None:
        return

    if args.no_send and not args.batch_only:
        summaries = load_post_summaries(settings.sqlite_path, run_id)
        text = format_digest_markdown(summaries)
        print("\n" + "=" * 60 + "\n")
        print(text[:8000])
        if len(text) > 8000:
            print(f"\n... [{len(text) - 8000} more chars]")


if __name__ == "__main__":
    asyncio.run(main())
