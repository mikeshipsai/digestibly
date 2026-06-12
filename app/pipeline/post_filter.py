"""Dedup and promo filtering before LLM summarization."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

from app.channels.preprocess import preprocess_post

logger = logging.getLogger(__name__)

_PROMO_STRONG_RE = re.compile(
    r"(?i)(erid=|\?erid=|промокод|кэшбэк|кешбэк|#реклама\b|"
    r"ya\.cc/t/|партнёрск|партнерск|sponsored|"
    r"запустите рекламу|яндекс директ|wildberries\.ru|ozon\.ru|"
    r"автоматическая скидка|суперцен[аы]\s*:)"
)

_PROMO_WEAK_RE = re.compile(
    r"(?i)(по ссылке|скидк[аи]\s*[\d%]+|заказать|горящий тур|"
    r"вылет\s+москва|кэшбэк|промо[\s-]?код)"
)


@dataclass(frozen=True, slots=True)
class PostFilterStats:
    input_posts: int
    promo_excluded: int
    deduped_posts: int
    output_posts: int

    @property
    def drop_rate(self) -> float:
        if self.input_posts == 0:
            return 0.0
        return (self.input_posts - self.output_posts) / self.input_posts


def post_content_hash(text: str) -> str:
    """Stable fingerprint for near-duplicate detection."""
    cleaned = preprocess_post(text).text_clean.casefold()
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def is_promo_post(text: str) -> bool:
    """Rule-based promo/ad detector."""
    if not text.strip():
        return False
    if _PROMO_STRONG_RE.search(text):
        return True
    return len(_PROMO_WEAK_RE.findall(text)) >= 2


def _engagement_raw(message: dict) -> float:
    return (
        int(message.get("views", 0) or 0)
        + 2 * int(message.get("reactions", 0) or 0)
        + 3 * int(message.get("replies", 0) or 0)
    )


def filter_messages_for_digest(
    messages_by_category: dict[str, list[dict]],
) -> tuple[dict[str, list[dict]], PostFilterStats]:
    """Remove promo posts and near-duplicates (keep higher engagement)."""
    input_posts = sum(len(messages) for messages in messages_by_category.values())
    promo_excluded = 0
    candidates: list[tuple[str, dict]] = []

    for category, messages in messages_by_category.items():
        for message in messages:
            text = str(message.get("text", ""))
            if is_promo_post(text):
                promo_excluded += 1
                continue
            candidates.append((category, message))

    best_by_hash: dict[str, tuple[str, dict]] = {}
    deduped_posts = 0
    for category, message in candidates:
        content_hash = post_content_hash(str(message.get("text", "")))
        enriched = {**message, "content_hash": content_hash}
        prev = best_by_hash.get(content_hash)
        if prev is None:
            best_by_hash[content_hash] = (category, enriched)
            continue
        deduped_posts += 1
        if _engagement_raw(enriched) > _engagement_raw(prev[1]):
            best_by_hash[content_hash] = (category, enriched)

    result: dict[str, list[dict]] = {}
    for category, message in best_by_hash.values():
        result.setdefault(category, []).append(message)

    for category in result:
        result[category].sort(
            key=lambda item: str(item.get("date", "")),
            reverse=True,
        )

    stats = PostFilterStats(
        input_posts=input_posts,
        promo_excluded=promo_excluded,
        deduped_posts=deduped_posts,
        output_posts=sum(len(messages) for messages in result.values()),
    )
    logger.info(
        "Post filter: input=%s promo=%s dedup=%s output=%s (drop_rate=%.0f%%)",
        stats.input_posts,
        stats.promo_excluded,
        stats.deduped_posts,
        stats.output_posts,
        stats.drop_rate * 100,
    )
    return result, stats
