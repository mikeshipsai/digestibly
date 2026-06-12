"""Shared types for the digest pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class PostSummary:
    """One selected post after LLM ranking for a category."""

    category: str
    channel: str
    title: str
    summary: str
    url: str
    rank: int


@dataclass(frozen=True, slots=True)
class ArticleSummary:
    """Stage-1 summary for a single post."""

    category: str
    channel: str
    title: str
    summary: str
    url: str
    views: int
    reactions: int
    replies: int
    engagement_score: float
    llm_relevance: float
    combined_score: float
    post_date: datetime

    @classmethod
    def from_message(cls, message: dict[str, Any], *, title: str, summary: str) -> ArticleSummary:
        date_obj = message.get("date")
        if not isinstance(date_obj, datetime):
            from datetime import datetime as dt

            date_obj = dt.now()
        return cls(
            category=str(message.get("category", "")),
            channel=str(message.get("channel", "")),
            title=title,
            summary=summary,
            url=str(message.get("url", "")),
            views=int(message.get("views", 0) or 0),
            reactions=int(message.get("reactions", 0) or 0),
            replies=int(message.get("replies", 0) or 0),
            engagement_score=float(message.get("engagement_score", 0.5)),
            llm_relevance=float(message.get("llm_relevance", 0.5)),
            combined_score=float(message.get("combined_score", 0.5)),
            post_date=date_obj,
        )
