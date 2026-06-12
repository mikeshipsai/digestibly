"""Engagement and combined interest scores for posts."""

from __future__ import annotations

import math
from typing import Any


def engagement_raw(views: int, reactions: int, replies: int) -> float:
    return math.log1p(max(views, 0)) + 2.0 * max(reactions, 0) + 3.0 * max(replies, 0)


def normalize_scores(values: list[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def combined_score(engagement_norm: float, llm_relevance: float) -> float:
    return 0.3 * engagement_norm + 0.7 * llm_relevance


def annotate_messages_with_scores(
    messages: list[dict[str, Any]],
    llm_relevance_by_url: dict[str, float],
) -> list[dict[str, Any]]:
    """Add engagement_score, llm_relevance, combined_score to each message dict."""
    if not messages:
        return []

    raw_scores = [
        engagement_raw(
            int(m.get("views", 0) or 0),
            int(m.get("reactions", 0) or 0),
            int(m.get("replies", 0) or 0),
        )
        for m in messages
    ]
    engagement_norms = normalize_scores(raw_scores)

    annotated: list[dict[str, Any]] = []
    for msg, eng_norm, raw in zip(messages, engagement_norms, raw_scores, strict=True):
        url = str(msg.get("url", ""))
        llm_rel = float(llm_relevance_by_url.get(url, 0.5))
        llm_rel = max(0.0, min(1.0, llm_rel))
        item = dict(msg)
        item["engagement_raw"] = raw
        item["engagement_score"] = eng_norm
        item["llm_relevance"] = llm_rel
        item["combined_score"] = combined_score(eng_norm, llm_rel)
        annotated.append(item)
    return annotated
