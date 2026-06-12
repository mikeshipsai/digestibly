"""Estimate LLM token usage (offline, chars/4 heuristic)."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.llm.summarizer import (
    SELECT_TOP_FROM_SUMMARIES_PROMPT,
    SUMMARIZE_BATCH_PROMPT,
    _build_post_chunks,
    _build_summary_chunks,
    _format_post_for_batch,
)

_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def estimate_digest_tokens(all_messages: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Estimate stage-1 (batch per theme) + stage-2 (top selection per category) requests."""
    top_n = get_settings().digest_top_n
    by_category: dict[str, dict[str, int]] = {}
    total_posts = 0
    stage1_tokens = 0
    stage2_tokens = 0
    stage1_requests = 0
    stage2_requests = 0

    for category, messages in all_messages.items():
        if not messages:
            continue

        chunks = _build_post_chunks(messages, category)
        cat_stage1 = sum(
            _estimate_tokens(
                SUMMARIZE_BATCH_PROMPT.format(
                    category=category,
                    posts_block="\n---\n".join(_format_post_for_batch(m) for m in chunk),
                )
            )
            for chunk in chunks
        )
        stage1_requests += len(chunks)

        pseudo_summaries = [
            {
                "title": "заголовок",
                "channel": message.get("channel", ""),
                "summary": "саммари" * 20,
                "combined_score": 0.5,
                "engagement_score": 0.5,
                "llm_relevance": 0.5,
                "url": message.get("url", ""),
            }
            for message in messages
        ]
        select_chunks = _build_summary_chunks(pseudo_summaries, category, top_n)
        cat_stage2 = sum(
            _estimate_tokens(
                SELECT_TOP_FROM_SUMMARIES_PROMPT.format(
                    category=category, summaries_text=ch, top_n=top_n
                )
            )
            for ch in select_chunks
        )
        stage2_requests += len(select_chunks)

        by_category[category] = {
            "posts": len(messages),
            "stage1_requests": len(chunks),
            "stage2_requests": len(select_chunks),
            "estimated_stage1_tokens": cat_stage1,
            "estimated_stage2_tokens": cat_stage2,
        }
        total_posts += len(messages)
        stage1_tokens += cat_stage1
        stage2_tokens += cat_stage2

    return {
        "total_posts": total_posts,
        "total_categories": len(by_category),
        "stage1_requests": stage1_requests,
        "stage2_requests": stage2_requests,
        "total_llm_requests": stage1_requests + stage2_requests,
        "estimated_stage1_tokens": stage1_tokens,
        "estimated_stage2_tokens": stage2_tokens,
        "estimated_input_tokens": stage1_tokens + stage2_tokens,
        "by_category": by_category,
    }
