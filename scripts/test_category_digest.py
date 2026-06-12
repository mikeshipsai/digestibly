"""Test digest for a single category: collect → batch summarize → top-N → send."""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
from pathlib import Path

from app.core.config import get_settings
from app.llm.summarizer import select_top_from_summaries, summarize_all_posts
from app.pipeline.post_filter import filter_messages_for_digest
from app.storage.posts import calendar_day_window, save_collected_posts
from app.storage.summaries import finish_digest_run, save_article_summaries, save_post_summaries, start_digest_run
from app.telegram import bot
from app.telegram.collector import _collect_channel_posts, _is_broadcast_channel, _iter_broadcast_entities
from app.telegram.userbot import connect_ephemeral

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_CATEGORY = "IT/Dev — Прод и инженерия"


def _load_usernames_for_category(csv_path: str, category: str) -> set[str]:
    usernames: set[str] = set()
    with Path(csv_path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("theme_cluster", "").strip() != category:
                continue
            username = row.get("username", "").strip().lstrip("@").lower()
            if username:
                usernames.add(username)
    return usernames


async def _collect_category(category: str, usernames: set[str]) -> list[dict]:
    settings = get_settings()
    since_dt, until_dt = calendar_day_window(settings.timezone, day_offset=-1)
    messages: list[dict] = []
    client = await connect_ephemeral()
    try:
        matched = 0
        async for entity in _iter_broadcast_entities(client):
            if not _is_broadcast_channel(entity):
                continue
            username = str(getattr(entity, "username", "") or "").lower()
            if username not in usernames:
                continue
            matched += 1
            bucket: dict[str, list[dict]] = {category: messages}
            await _collect_channel_posts(
                client,
                entity=entity,
                category=category,
                since_dt=since_dt,
                until_dt=until_dt,
                result=bucket,
            )
        logger.info("Matched %s/%s channels from CSV for %s", matched, len(usernames), category)
    finally:
        await client.disconnect()
    return messages


def _articles_to_selection_dicts(articles) -> list[dict]:
    return [
        {
            "title": article.title,
            "channel": article.channel,
            "summary": article.summary,
            "url": article.url,
            "combined_score": article.combined_score,
            "engagement_score": article.engagement_score,
            "llm_relevance": article.llm_relevance,
        }
        for article in articles
    ]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run digest for one category only")
    parser.add_argument("--category", default=DEFAULT_CATEGORY, help="Theme name from channels.csv")
    parser.add_argument("--top-n", type=int, default=5, help="How many posts to pick")
    parser.add_argument("--no-send", action="store_true", help="Skip Telegram delivery")
    parser.add_argument("--no-collect", action="store_true", help="Use posts already in SQLite for this category")
    args = parser.parse_args()

    settings = get_settings()
    category = args.category.strip()
    usernames = _load_usernames_for_category(settings.channels_csv_path, category)
    if not usernames:
        logger.error("No channels in %s for category %r", settings.channels_csv_path, category)
        return

    logger.info("Category: %s | channels: %s", category, ", ".join(sorted(usernames)))

    if args.no_collect:
        from app.storage.posts import load_posts_grouped

        all_messages = load_posts_grouped(settings.sqlite_path)
        messages = all_messages.get(category, [])
    else:
        messages = await _collect_category(category, usernames)
        if messages:
            save_collected_posts({category: messages}, settings.sqlite_path)

    filtered, _ = filter_messages_for_digest({category: messages})
    messages = filtered.get(category, [])
    logger.info("Posts after filter: %s", len(messages))
    if not messages:
        logger.warning("No posts for yesterday in category %s", category)
        if not args.no_send:
            await bot.send_digest(f"За вчера в категории «{category}» постов не найдено.", settings.owner_chat_id)
        return

    run_id = start_digest_run(
        settings.sqlite_path,
        posts_collected=len(messages),
        categories_count=1,
        run_type="batch",
    )

    articles = await summarize_all_posts({category: messages})
    save_article_summaries(settings.sqlite_path, run_id, articles)
    finish_digest_run(settings.sqlite_path, run_id)
    logger.info("Summarized %s posts (run_id=%s)", len(articles), run_id)

    digest_run_id = start_digest_run(
        settings.sqlite_path,
        posts_collected=len(articles),
        categories_count=1,
        run_type="digest",
    )
    picked = await select_top_from_summaries(category, _articles_to_selection_dicts(articles))
    if args.top_n:
        picked = picked[: args.top_n]
    save_post_summaries(settings.sqlite_path, digest_run_id, picked)
    finish_digest_run(settings.sqlite_path, digest_run_id)

    logger.info("Selected %s posts for %s", len(picked), category)
    for item in picked:
        logger.info("  #%s %s — %s", item.rank, item.title, item.url)

    if args.no_send:
        return

    await bot.send_single_category_digest(category, picked, settings.owner_chat_id)
    logger.info("Sent digest to chat %s", settings.owner_chat_id)


if __name__ == "__main__":
    asyncio.run(main())
