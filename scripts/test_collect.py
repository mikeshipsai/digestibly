"""Test run: collect yesterday's posts, save to SQLite, estimate tokens."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from app.core.config import get_settings
from app.llm.token_estimate import estimate_digest_tokens
from app.pipeline.post_filter import filter_messages_for_digest
from app.storage.posts import count_posts, save_collected_posts
from app.telegram.collector import collect_messages

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    logger.info("Starting test collection (yesterday, max %s posts/channel)", 50)

    all_messages = await collect_messages(standalone=True)
    total_raw = sum(len(msgs) for msgs in all_messages.values())
    all_messages, filter_stats = filter_messages_for_digest(all_messages)
    logger.info(
        "Post filter: input=%s promo=%s dedup=%s output=%s",
        filter_stats.input_posts,
        filter_stats.promo_excluded,
        filter_stats.deduped_posts,
        filter_stats.output_posts,
    )
    if total_raw == 0:
        logger.warning("No posts collected for yesterday")
        sys.exit(0)

    inserted = save_collected_posts(all_messages, settings.sqlite_path)
    total_in_db = count_posts(settings.sqlite_path)
    token_stats = estimate_digest_tokens(all_messages)

    logger.info("Collection done: %s posts in memory, %s new rows in DB", total_raw, inserted)
    logger.info("SQLite: %s (total rows: %s)", settings.sqlite_path, total_in_db)
    logger.info("Token estimate (chars/4 heuristic):")
    logger.info("  categories: %s", token_stats["total_categories"])
    logger.info("  posts: %s", token_stats["total_posts"])
    logger.info("  stage-1 requests: %s (~%s tokens)", token_stats["stage1_requests"], token_stats["estimated_stage1_tokens"])
    logger.info("  stage-2 requests: %s (~%s tokens)", token_stats["stage2_requests"], token_stats["estimated_stage2_tokens"])
    logger.info("  total LLM requests: %s", token_stats["total_llm_requests"])
    logger.info("  estimated input tokens: ~%s", token_stats["estimated_input_tokens"])

    for category, stats in sorted(token_stats["by_category"].items(), key=lambda x: -x[1]["posts"]):
        logger.info(
            "  [%s] posts=%s stage1=%s stage2=%s tokens~%s",
            category,
            stats["posts"],
            stats["stage1_requests"],
            stats["stage2_requests"],
            stats["estimated_stage1_tokens"] + stats["estimated_stage2_tokens"],
        )

    report_path = str(Path(settings.sqlite_path).with_name("token_report.json"))
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(token_stats, fh, ensure_ascii=False, indent=2)
    logger.info("Token report saved: %s", report_path)


if __name__ == "__main__":
    asyncio.run(main())
