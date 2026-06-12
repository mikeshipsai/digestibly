"""LLM: stage-1 batch summary per theme, stage-2 top selection from summaries."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from typing import Any

from app.core.config import get_settings
from app.llm.llm_client import call_llm
from app.pipeline.scoring import annotate_messages_with_scores
from app.pipeline.types import ArticleSummary, PostSummary

logger = logging.getLogger(__name__)

SUMMARIZE_BATCH_PROMPT = """
Ты — редактор персонального дайджеста Telegram-каналов.

Категория: {category}

Посты (у каждого есть url — верни его без изменений):
{posts_block}

Задача: сделай саммари каждого поста для дайджеста.

Ответь ТОЛЬКО валидным JSON-массивом без markdown-обёртки. Каждый элемент:
{{
  "url": "точная ссылка из входных данных",
  "title": "краткий заголовок на русском (1 строка)",
  "summary": "суть поста в 4-5 предложениях на русском",
  "llm_relevance": 0.85
}}

Правила:
- ровно один элемент на каждый url из входа
- url должен совпадать с одним из url во входе
- llm_relevance — число от 0.0 до 1.0: насколько пост важен и актуален для читателя сегодня
- тизеры без конкретики (угадайте, скоро, анонс без деталей, интрига без сути) — llm_relevance 0.2–0.4
- посты с практической ценностью, релизами, инструментами, исследованиями — llm_relevance 0.7–1.0
"""

SUMMARIZE_POST_PROMPT = """
Ты — редактор персонального дайджеста Telegram-каналов.

Канал: {channel}
Пост:
{text}

Задача: сделай саммари поста для дайджеста.

Ответь ТОЛЬКО валидным JSON без markdown-обёртки:
{{
  "title": "краткий заголовок на русском (1 строка)",
  "summary": "суть поста в 4-5 предложениях на русском",
  "llm_relevance": 0.85
}}

Поле llm_relevance — число от 0.0 до 1.0: насколько пост важен и актуален для читателя сегодня.
Тизеры без конкретики — 0.2–0.4; практичные посты с релизами и инструментами — 0.7–1.0.
"""

SELECT_TOP_FROM_SUMMARIES_PROMPT = """
Ты — редактор персонального дайджеста Telegram-каналов.

Категория: {category}

Саммари постов за вчера (у каждого есть score = 0.3×engagement + 0.7×llm_relevance):
{summaries_text}

Задача: выбери до {top_n} самых интересных постов. Учитывай score, но не выбирай только по нему —
важна и содержательная ценность.

Ответь ТОЛЬКО валидным JSON-массивом без markdown-обёртки. Каждый элемент:
{{
  "url": "точная ссылка из входных данных"
}}

Правила:
- url должен совпадать с одной из ссылок во входе
- не больше {top_n} элементов
- если постов нет или все слабые — верни []
"""

# Groq free tier: 6000 tokens/min. Russian text ≈ 2 chars/token, so a prompt
# must stay well under ~8K chars to fit a request + response in the TPM budget.
MAX_PROMPT_LENGTH = 8_000
MESSAGE_TEXT_LIMIT = 1_000
BATCH_POSTS_PER_CHUNK = 8


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _format_post_for_batch(message: dict[str, Any]) -> str:
    text = str(message.get("text", ""))[:MESSAGE_TEXT_LIMIT]
    return (
        f"url: {message.get('url', '')}\n"
        f"канал: {message.get('channel', '')}\n"
        f"текст:\n{text}"
    )


def _build_post_chunks(messages: list[dict[str, Any]], category: str) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    for message in messages:
        tentative = current + [message]
        posts_block = "\n---\n".join(_format_post_for_batch(m) for m in tentative)
        prompt = SUMMARIZE_BATCH_PROMPT.format(category=category, posts_block=posts_block)
        over_limit = len(prompt) > MAX_PROMPT_LENGTH or len(tentative) > BATCH_POSTS_PER_CHUNK
        if over_limit and current:
            chunks.append(current)
            current = [message]
        else:
            current.append(message)

    if current:
        chunks.append(current)
    return chunks


def _require_summary_fields(title: str, summary: str, *, url: str) -> tuple[str, str]:
    title = title.strip()
    summary = summary.strip()
    if not title or not summary:
        raise ValueError(f"LLM returned empty title/summary for {url}")
    return title, summary


def _parse_batch_item(
    item: dict[str, Any],
    message_by_url: dict[str, dict[str, Any]],
) -> tuple[str, tuple[str, str, float]] | None:
    url = str(item.get("url", "")).strip()
    if not url or url not in message_by_url:
        return None

    title = str(item.get("title", "")).strip()
    summary = str(item.get("summary", "")).strip()
    try:
        relevance = float(item.get("llm_relevance", 0.5))
    except (TypeError, ValueError):
        relevance = 0.5
    relevance = max(0.0, min(1.0, relevance))
    title, summary = _require_summary_fields(title, summary, url=url)
    return url, (title, summary, relevance)


def _format_summary_for_selection(item: dict[str, Any]) -> str:
    return (
        f"Заголовок: {item.get('title', '')}\n"
        f"Канал: {item.get('channel', '')}\n"
        f"Саммари: {item.get('summary', '')}\n"
        f"score: {float(item.get('combined_score', 0)):.2f} "
        f"(engagement={float(item.get('engagement_score', 0)):.2f}, "
        f"llm={float(item.get('llm_relevance', 0)):.2f})\n"
        f"Ссылка: {item.get('url', '')}"
    )


def _build_summary_chunks(summaries: list[dict[str, Any]], category: str, top_n: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []

    for item in summaries:
        formatted = _format_summary_for_selection(item)
        tentative = "\n---\n".join(current + [formatted])
        prompt = SELECT_TOP_FROM_SUMMARIES_PROMPT.format(
            category=category, summaries_text=tentative, top_n=top_n
        )
        if len(prompt) > MAX_PROMPT_LENGTH and current:
            chunks.append("\n---\n".join(current))
            current = [formatted]
        else:
            current.append(formatted)

    if current:
        chunks.append("\n---\n".join(current))
    return chunks


async def summarize_post(message: dict[str, Any]) -> tuple[str, str, float]:
    """Summarize a single post via LLM. Returns (title, summary, llm_relevance)."""
    text = str(message.get("text", ""))[:MESSAGE_TEXT_LIMIT]
    url = str(message.get("url", ""))
    prompt = SUMMARIZE_POST_PROMPT.format(channel=message.get("channel", ""), text=text)
    raw = await call_llm(prompt)
    data = _extract_json_object(raw)
    title = str(data.get("title", "")).strip()
    summary = str(data.get("summary", "")).strip()
    try:
        relevance = float(data.get("llm_relevance", 0.5))
    except (TypeError, ValueError):
        relevance = 0.5
    relevance = max(0.0, min(1.0, relevance))
    title, summary = _require_summary_fields(title, summary, url=url)
    return title, summary, relevance


async def _call_batch_summarize(
    category: str,
    messages: list[dict[str, Any]],
    message_by_url: dict[str, dict[str, Any]],
) -> dict[str, tuple[str, str, float]]:
    posts_block = "\n---\n".join(_format_post_for_batch(m) for m in messages)
    prompt = SUMMARIZE_BATCH_PROMPT.format(category=category, posts_block=posts_block)
    raw = await call_llm(prompt)

    results: dict[str, tuple[str, str, float]] = {}
    for item in _extract_json_array(raw):
        if not isinstance(item, dict):
            continue
        parsed = _parse_batch_item(item, message_by_url)
        if parsed is None:
            continue
        url, summary_tuple = parsed
        if url not in results:
            results[url] = summary_tuple
    return results


async def _summarize_missing_posts(
    messages: list[dict[str, Any]],
    results: dict[str, tuple[str, str, float]],
) -> None:
    for message in messages:
        url = str(message.get("url", ""))
        if url in results:
            continue
        results[url] = await summarize_post(message)


async def _summarize_messages_chunk(
    category: str,
    messages: list[dict[str, Any]],
) -> dict[str, tuple[str, str, float]]:
    message_by_url = {str(m.get("url", "")): m for m in messages}
    try:
        results = await _call_batch_summarize(category, messages, message_by_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Batch chunk failed for %s (%s posts): %s", category, len(messages), exc)
        if len(messages) == 1:
            url = str(messages[0].get("url", ""))
            return {url: await summarize_post(messages[0])}
        mid = len(messages) // 2
        left = await _summarize_messages_chunk(category, messages[:mid])
        right = await _summarize_messages_chunk(category, messages[mid:])
        return {**left, **right}

    await _summarize_missing_posts(messages, results)
    return results


async def summarize_posts_batch(
    category: str,
    messages: list[dict[str, Any]],
) -> dict[str, tuple[str, str, float]]:
    """Summarize all posts in a category via batched LLM calls."""
    if not messages:
        return {}

    results: dict[str, tuple[str, str, float]] = {}
    chunks = _build_post_chunks(messages, category)
    for idx, chunk in enumerate(chunks, start=1):
        logger.info(
            "LLM summarize batch | %s | chunk %s/%s (%s posts)",
            category,
            idx,
            len(chunks),
            len(chunk),
        )
        chunk_results = await _summarize_messages_chunk(category, chunk)
        results.update(chunk_results)
    return results


async def summarize_all_posts(
    messages_by_category: dict[str, list[dict[str, Any]]],
) -> list[ArticleSummary]:
    """Stage 1: summarize every post and compute combined scores per category."""
    articles: list[ArticleSummary] = []
    for category, messages in sorted(messages_by_category.items()):
        if not messages:
            continue

        batch_results = await summarize_posts_batch(category, messages)
        relevance_by_url = {url: rel for url, (_, _, rel) in batch_results.items()}
        titles_by_url = {url: title for url, (title, _, _) in batch_results.items()}
        summaries_by_url = {url: summary for url, (_, summary, _) in batch_results.items()}

        annotated = annotate_messages_with_scores(messages, relevance_by_url)
        for msg in annotated:
            url = str(msg.get("url", ""))
            if url not in batch_results:
                logger.warning("Skipping post without LLM summary: %s", url)
                continue
            articles.append(
                ArticleSummary.from_message(
                    {**msg, "category": category},
                    title=titles_by_url[url],
                    summary=summaries_by_url[url],
                )
            )
    return articles


def _pick_top_by_score(
    category: str,
    summaries: list[dict[str, Any]],
    *,
    top_n: int,
) -> list[PostSummary]:
    sorted_items = sorted(summaries, key=lambda x: float(x.get("combined_score", 0)), reverse=True)
    picked: list[PostSummary] = []
    for item in sorted_items[:top_n]:
        picked.append(
            PostSummary(
                category=category,
                channel=str(item.get("channel", "")),
                title=str(item.get("title", "")),
                summary=str(item.get("summary", "")),
                url=str(item.get("url", "")),
                rank=0,
            )
        )
    return [replace(p, rank=i + 1) for i, p in enumerate(picked)]


async def select_top_from_summaries(
    category: str,
    summaries: list[dict[str, Any]],
) -> list[PostSummary]:
    """Stage 2: pick top-N posts from pre-summarized articles."""
    if not summaries:
        return []

    top_n = get_settings().digest_top_n
    if len(summaries) <= top_n:
        return _pick_top_by_score(category, summaries, top_n=len(summaries))

    chunks = _build_summary_chunks(summaries, category, top_n)
    selected_urls: list[str] = []
    seen: set[str] = set()

    for idx, chunk in enumerate(chunks, start=1):
        prompt = SELECT_TOP_FROM_SUMMARIES_PROMPT.format(
            category=category, summaries_text=chunk, top_n=top_n
        )
        logger.info("LLM select top | %s | chunk %s/%s", category, idx, len(chunks))
        raw = await call_llm(prompt)
        for item in _extract_json_array(raw):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if url and url not in seen:
                seen.add(url)
                selected_urls.append(url)

    by_url = {str(s["url"]): s for s in summaries}
    picked: list[PostSummary] = []
    for url in selected_urls[:top_n]:
        src = by_url.get(url)
        if not src:
            continue
        picked.append(
            PostSummary(
                category=category,
                channel=str(src.get("channel", "")),
                title=str(src.get("title", "")),
                summary=str(src.get("summary", "")),
                url=url,
                rank=0,
            )
        )

    if not picked:
        logger.warning("LLM returned no top posts for %s — using score order", category)
        return _pick_top_by_score(category, summaries, top_n=top_n)

    return [replace(p, rank=i + 1) for i, p in enumerate(picked)]
