"""Daily digest pipeline: night batch (collect+summarize) + morning send (top-5)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from app.channels.macro_themes import MACRO_THEMES, merge_to_macro_themes, to_macro_theme
from app.core.config import get_settings
from app.llm.summarizer import select_top_from_summaries, summarize_all_posts
from app.pipeline.format import digest_target_date, format_digest_date
from app.pipeline.post_filter import filter_messages_for_digest
from app.pipeline.themes_merge import merge_small_themes
from app.pipeline.types import ArticleSummary, PostSummary
from app.storage.posts import delete_posts_older_than, load_posts_grouped, save_collected_posts
from app.storage.summaries import (
    delete_old_runs,
    finish_digest_run,
    get_latest_run_id,
    load_article_summaries_grouped,
    load_post_summaries,
    save_article_summaries,
    save_post_summaries,
    start_digest_run,
)
from app.storage.themes import list_channels_by_theme
from app.telegram import bot
from app.telegram.collector import collect_messages, collect_messages_for_category

logger = logging.getLogger(__name__)

_pipeline_lock = asyncio.Lock()
_last_digest_at: Optional[datetime] = None
_last_batch_at: Optional[datetime] = None
_last_run_id: Optional[int] = None
_last_batch_run_id: Optional[int] = None


def get_last_digest_time() -> Optional[datetime]:
    return _last_digest_at


def get_last_batch_time() -> Optional[datetime]:
    return _last_batch_at


def _merge_categories(messages: dict) -> dict:
    settings = get_settings()
    macro = merge_to_macro_themes(messages)
    return merge_small_themes(macro, min_posts=settings.min_posts_per_theme)


def _list_known_themes() -> list[str]:
    return list(MACRO_THEMES)


def resolve_theme_name(query: str) -> str:
    query = query.strip()
    if not query:
        raise ValueError("Укажите название темы, например: ML и AI")
    themes = _list_known_themes()
    if query in themes:
        return query
    by_lower = {theme.lower(): theme for theme in themes}
    resolved = by_lower.get(query.lower())
    if resolved:
        return resolved
    macro = to_macro_theme(query)
    if macro in themes:
        return macro
    raise ValueError(f"Тема «{query}» не найдена. Доступно: {', '.join(themes)}")


def _usernames_for_theme(category: str) -> set[str]:
    mapping = list_channels_by_theme(category)
    usernames: set[str] = set()
    for channel_key in mapping:
        if channel_key.startswith("@"):
            usernames.add(channel_key.lstrip("@").lower())
    return usernames


def _articles_to_selection_dicts(articles: list[ArticleSummary]) -> list[dict[str, Any]]:
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


async def run_night_batch(*, collect: bool = True) -> int | None:
    """Stage 1: collect yesterday's posts, summarize all, save to DB."""
    async with _pipeline_lock:
        return await _run_night_batch_locked(collect=collect)


async def _run_night_batch_locked(*, collect: bool = True) -> int | None:
    global _last_batch_at, _last_batch_run_id
    settings = get_settings()
    logger.info("Night batch started (collect=%s)", collect)

    if collect:
        all_messages = await collect_messages()
    else:
        all_messages = load_posts_grouped(settings.sqlite_path)

    all_messages = _merge_categories(all_messages)
    all_messages, _ = filter_messages_for_digest(all_messages)
    total_posts = sum(len(m) for m in all_messages.values())
    categories_with_posts = len([c for c, m in all_messages.items() if m])

    for category, messages in all_messages.items():
        logger.info("Category %s: %s messages", category, len(messages))

    if collect:
        inserted = save_collected_posts(all_messages, settings.sqlite_path)
        logger.info("Saved %s new posts to collected_posts", inserted)

    run_id = start_digest_run(
        settings.sqlite_path,
        posts_collected=total_posts,
        categories_count=categories_with_posts,
        run_type="batch",
    )
    _last_batch_run_id = run_id

    if settings.debug_collect_only:
        finish_digest_run(settings.sqlite_path, run_id)
        _last_batch_at = datetime.now()
        logger.info("DEBUG_COLLECT_ONLY: stopped after collect")
        return run_id

    if total_posts == 0:
        finish_digest_run(settings.sqlite_path, run_id)
        _last_batch_at = datetime.now()
        logger.info("No posts to summarize in night batch")
        return run_id

    articles = await summarize_all_posts(all_messages)
    saved = save_article_summaries(settings.sqlite_path, run_id, articles)
    logger.info("Saved %s article summaries (run_id=%s)", saved, run_id)

    finish_digest_run(settings.sqlite_path, run_id)
    _last_batch_at = datetime.now()
    logger.info("Night batch completed, run_id=%s", run_id)
    return run_id


async def run_morning_digest(
    *,
    send_telegram: bool = True,
    batch_run_id: int | None = None,
) -> int | None:
    """Stage 2: select top-5 per theme from batch summaries and send."""
    async with _pipeline_lock:
        return await _run_morning_digest_locked(
            send_telegram=send_telegram,
            batch_run_id=batch_run_id,
        )


async def _run_morning_digest_locked(
    *,
    send_telegram: bool = True,
    batch_run_id: int | None = None,
) -> int | None:
    global _last_digest_at, _last_run_id
    settings = get_settings()

    source_run_id = batch_run_id or get_latest_run_id(settings.sqlite_path, run_type="batch")
    if source_run_id is None:
        logger.warning("No batch run found — running night batch first")
        source_run_id = await _run_night_batch_locked()
        if source_run_id is None:
            return None

    summaries_by_category = load_article_summaries_grouped(settings.sqlite_path, source_run_id)
    summaries_by_category = _merge_categories(summaries_by_category)

    total = sum(len(v) for v in summaries_by_category.values())
    run_id = start_digest_run(
        settings.sqlite_path,
        posts_collected=total,
        categories_count=len([c for c, m in summaries_by_category.items() if m]),
        run_type="digest",
    )
    _last_run_id = run_id

    if total == 0:
        finish_digest_run(settings.sqlite_path, run_id)
        if send_telegram:
            await bot.send_digest("За вчера новых постов не найдено.", settings.owner_chat_id)
        return run_id

    all_picked: list[PostSummary] = []
    for category, summaries in sorted(summaries_by_category.items()):
        if not summaries:
            continue
        picked = await select_top_from_summaries(category, summaries)
        logger.info("Category %s: selected %s posts", category, len(picked))
        all_picked.extend(picked)

    save_post_summaries(settings.sqlite_path, run_id, all_picked)
    selected_by_category = load_post_summaries(settings.sqlite_path, run_id)

    if send_telegram:
        await bot.send_digest_by_category(selected_by_category, settings.owner_chat_id)
        logger.info("Digest sent by category to chat %s", settings.owner_chat_id)

    deleted = delete_posts_older_than(settings.sqlite_path, days=2)
    logger.info("Deleted %s old collected posts", deleted)
    keep_ids = {run_id, source_run_id}
    delete_old_runs(settings.sqlite_path, keep_ids)

    finish_digest_run(settings.sqlite_path, run_id)
    _last_digest_at = datetime.now()
    logger.info("Morning digest completed, run_id=%s", run_id)
    return run_id


async def run_digest_theme(
    category_query: str,
    *,
    send_telegram: bool = True,
    collect: bool = True,
) -> int | None:
    """Collect, summarize and send digest for a single theme."""
    async with _pipeline_lock:
        settings = get_settings()
        category = resolve_theme_name(category_query)
        usernames = _usernames_for_theme(category)
        if not usernames:
            raise ValueError(f"Нет каналов для темы «{category}»")

        logger.info("Theme digest started: %s (%s channels)", category, len(usernames))

        if collect:
            messages = await collect_messages_for_category(category, usernames)
            if messages:
                save_collected_posts({category: messages}, settings.sqlite_path)
        else:
            all_messages = load_posts_grouped(settings.sqlite_path)
            messages = all_messages.get(category, [])

        filtered, _ = filter_messages_for_digest({category: messages})
        messages = filtered.get(category, [])
        digest_date = digest_target_date(settings.timezone)

        if not messages:
            if send_telegram:
                date_label = format_digest_date(digest_date)
                await bot.send_digest(
                    f"За {date_label} в теме «{category}» постов не найдено.",
                    settings.owner_chat_id,
                )
            return None

        batch_run_id = start_digest_run(
            settings.sqlite_path,
            posts_collected=len(messages),
            categories_count=1,
            run_type="batch",
        )
        articles = await summarize_all_posts({category: messages})
        save_article_summaries(settings.sqlite_path, batch_run_id, articles)
        finish_digest_run(settings.sqlite_path, batch_run_id)

        digest_run_id = start_digest_run(
            settings.sqlite_path,
            posts_collected=len(articles),
            categories_count=1,
            run_type="digest",
        )
        picked = await select_top_from_summaries(category, _articles_to_selection_dicts(articles))
        save_post_summaries(settings.sqlite_path, digest_run_id, picked)
        finish_digest_run(settings.sqlite_path, digest_run_id)

        if send_telegram:
            await bot.send_single_category_digest(category, picked, settings.owner_chat_id)

        logger.info("Theme digest completed: %s (%s posts)", category, len(picked))
        return digest_run_id


async def run_digest(
    *,
    send_telegram: bool = True,
    collect: bool = True,
    force_full: bool = False,
) -> int | None:
    """Full manual pipeline: batch + morning digest in one go."""
    async with _pipeline_lock:
        settings = get_settings()
        logger.info("Full digest pipeline (collect=%s, send=%s)", collect, send_telegram)

        batch_run_id = await _run_night_batch_locked(collect=collect)
        if batch_run_id is None:
            return None

        if settings.debug_collect_only and not force_full:
            return batch_run_id

        return await _run_morning_digest_locked(
            send_telegram=send_telegram,
            batch_run_id=batch_run_id,
        )
