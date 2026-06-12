"""LLM-based channel theme classification with SQLite cache."""

from __future__ import annotations

import json
import logging
import re

from app.channels.cluster import infer_theme_cluster
from app.channels.macro_themes import DEFAULT_MACRO_THEME, MACRO_THEMES, to_macro_theme
from app.core.config import get_settings
from app.llm.llm_client import call_llm
from app.storage.themes import (
    get_ai_theme,
    list_custom_themes,
    load_all_ai_themes,
    normalize_channel_key,
    save_ai_theme,
)

logger = logging.getLogger(__name__)

_POSTS_CLASSIFY_PROMPT = """
Ты классифицируешь Telegram-канал по темам для персонального дайджеста.

Доступные темы (выбери ОДНУ):
{themes_list}

Канал: {title}
{about_line}
Примеры постов:
{posts_block}

Ответь ТОЛЬКО валидным JSON без markdown:
{{"theme": "точное название темы из списка", "summary": "одно предложение о канале"}}
"""

_BATCH_CLASSIFY_PROMPT = """
Ты классифицируешь Telegram-каналы по темам для персонального дайджеста.

Доступные темы (выбери для каждого канала ОДНУ):
{themes_list}

Каналы:
{channels_block}

Ответь ТОЛЬКО валидным JSON-массивом без markdown. Каждый элемент:
{{"id": "точный id из входа", "theme": "точное название темы из списка"}}
"""

_BATCH_SIZE = 8
PROFILE_POSTS_LIMIT = 10


def available_themes() -> list[str]:
    themes = list(MACRO_THEMES)
    for custom in list_custom_themes():
        macro = to_macro_theme(custom)
        if macro not in themes:
            themes.append(macro)
    return themes


def _extract_json_array(text: str) -> list[dict]:
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


def _extract_json_object(text: str) -> dict:
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


def _pick_closest_theme(raw: str, candidates: list[str]) -> str:
    raw = raw.strip()
    if raw in candidates:
        return raw
    macro = to_macro_theme(raw)
    if macro in candidates:
        return macro
    raw_lower = raw.lower()
    for theme in candidates:
        if theme.lower() == raw_lower:
            return theme
    for theme in candidates:
        if raw_lower in theme.lower() or theme.lower() in raw_lower:
            return theme
    return to_macro_theme(infer_theme_cluster(raw) if raw else DEFAULT_MACRO_THEME)


def _save_theme(channel_key: str, theme: str) -> str:
    macro = to_macro_theme(theme)
    save_ai_theme(channel_key, macro)
    return macro


def _keyword_classify(title: str, about: str) -> str:
    return to_macro_theme(infer_theme_cluster(title, about))


def _format_posts_block(posts: list[str]) -> str:
    lines: list[str] = []
    for idx, post in enumerate(posts[:PROFILE_POSTS_LIMIT], start=1):
        snippet = post.strip().replace("\n", " ")
        if len(snippet) > 400:
            snippet = snippet[:397] + "..."
        if snippet:
            lines.append(f"{idx}. {snippet}")
    return "\n".join(lines) if lines else "(нет текстовых постов)"


async def classify_channel_by_posts(
    title: str,
    about: str,
    posts: list[str],
    *,
    username: str | None = None,
    use_cache: bool = True,
) -> str:
    """Classify channel by profile posts; cache macro theme in SQLite."""
    channel_key = normalize_channel_key(username, title)
    if use_cache:
        cached = get_ai_theme(channel_key)
        if cached:
            return to_macro_theme(cached)

    keyword_theme = _keyword_classify(title, about)
    if keyword_theme != DEFAULT_MACRO_THEME and posts:
        return _save_theme(channel_key, keyword_theme)

    settings = get_settings()
    if not settings.ai_cluster_enabled or not posts:
        return _save_theme(channel_key, keyword_theme)

    candidates = available_themes()
    about_line = f"Описание: {about}" if about.strip() else ""
    prompt = _POSTS_CLASSIFY_PROMPT.format(
        themes_list="\n".join(f"- {t}" for t in candidates),
        title=title,
        about_line=about_line,
        posts_block=_format_posts_block(posts),
    )
    try:
        raw = await call_llm(prompt)
        parsed = _extract_json_object(raw)
        theme = _pick_closest_theme(str(parsed.get("theme", "")), candidates)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Posts classify failed for %s: %s — keyword fallback", channel_key, exc)
        theme = keyword_theme

    return _save_theme(channel_key, theme)


async def classify_channel_theme(
    title: str,
    about: str,
    *,
    username: str | None = None,
    use_cache: bool = True,
) -> str:
    """Classify one channel by title/about; cache result in SQLite."""
    channel_key = normalize_channel_key(username, title)
    if use_cache:
        cached = get_ai_theme(channel_key)
        if cached:
            return to_macro_theme(cached)

    theme = _keyword_classify(title, about)
    if theme != DEFAULT_MACRO_THEME:
        return _save_theme(channel_key, theme)

    settings = get_settings()
    if not settings.ai_cluster_enabled:
        return _save_theme(channel_key, theme)

    candidates = available_themes()
    batch_result = await _classify_batch_llm(
        [{"id": channel_key, "title": title, "about": about, "username": username}],
        candidates,
    )
    theme = batch_result.get(channel_key, theme)
    return _save_theme(channel_key, theme)


async def _classify_batch_llm(
    items: list[dict],
    candidates: list[str],
) -> dict[str, str]:
    """Classify up to N channels in one LLM request."""
    if not items:
        return {}

    lines = []
    for item in items:
        cid = str(item["id"])
        title = str(item.get("title", ""))
        about = str(item.get("about", "") or "(нет описания)")
        lines.append(f'id: {cid}\nНазвание: {title}\nОписание: {about}')

    prompt = _BATCH_CLASSIFY_PROMPT.format(
        themes_list="\n".join(f"- {t}" for t in candidates),
        channels_block="\n---\n".join(lines),
    )
    try:
        raw = await call_llm(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI batch cluster failed: %s — keyword fallback", exc)
        return {
            str(item["id"]): _keyword_classify(
                str(item.get("title", "")),
                str(item.get("about", "")),
            )
            for item in items
        }

    by_id = {str(item["id"]): item for item in items}
    result: dict[str, str] = {}
    for entry in _extract_json_array(raw):
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("id", "")).strip()
        if cid not in by_id:
            continue
        item = by_id[cid]
        theme = _pick_closest_theme(str(entry.get("theme", "")), candidates)
        result[cid] = theme

    for item in items:
        cid = str(item["id"])
        if cid not in result:
            result[cid] = _keyword_classify(
                str(item.get("title", "")),
                str(item.get("about", "")),
            )
    return result


async def classify_new_channels_by_posts(
    channels: list[dict],
    *,
    posts_fetcher,
) -> None:
    """Classify channels without AI cache using profile posts (batched LLM)."""
    settings = get_settings()
    if not settings.ai_cluster_enabled:
        return

    cached = load_all_ai_themes()
    pending: list[dict] = []

    for ch in channels:
        title = str(ch.get("title", ""))
        about = str(ch.get("about", ""))
        username = ch.get("username")
        key = normalize_channel_key(username, title)
        if key in cached:
            continue
        entity = ch.get("entity")
        posts: list[str] = []
        if entity is not None:
            posts = await posts_fetcher(entity)
        pending.append(
            {
                "id": key,
                "title": title,
                "about": about,
                "username": username,
                "posts": posts,
            }
        )

    if not pending:
        return

    logger.info("Classifying %s channels by posts", len(pending))

    for item in pending:
        posts = list(item.get("posts") or [])
        if posts:
            await classify_channel_by_posts(
                str(item["title"]),
                str(item.get("about", "")),
                posts,
                username=item.get("username"),
                use_cache=False,
            )
        else:
            keyword = _keyword_classify(str(item["title"]), str(item.get("about", "")))
            _save_theme(str(item["id"]), keyword)


async def ensure_channels_classified(channels: list[dict]) -> None:
    """Legacy entry: classify uncached channels by title/about (keywords + LLM)."""
    settings = get_settings()
    if not settings.ai_cluster_enabled:
        return

    cached = load_all_ai_themes()
    pending_llm: list[dict] = []

    for ch in channels:
        title = str(ch.get("title", ""))
        about = str(ch.get("about", ""))
        username = ch.get("username")
        key = normalize_channel_key(username, title)
        if key in cached:
            continue

        keyword_theme = _keyword_classify(title, about)
        if keyword_theme != DEFAULT_MACRO_THEME:
            _save_theme(key, keyword_theme)
            cached[key] = keyword_theme
            continue

        pending_llm.append({"id": key, "title": title, "about": about, "username": username})

    if not pending_llm:
        return

    candidates = available_themes()
    logger.info("AI cluster: %s channels need LLM (batched by %s)", len(pending_llm), _BATCH_SIZE)

    for start in range(0, len(pending_llm), _BATCH_SIZE):
        batch = pending_llm[start : start + _BATCH_SIZE]
        classified = await _classify_batch_llm(batch, candidates)
        for key, theme in classified.items():
            _save_theme(key, theme)
