"""Heuristic thematic clustering for Telegram channels."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Final

# --- Top-level themes (non ML/IT) ---
TOP_LEVEL_THEMES: Final[dict[str, tuple[str, ...]]] = {
    "Крипто/Финансы": (
        "crypto", "bitcoin", "btc", "eth", "блокчейн", "трейдинг", "инвест", "финанс",
        "биржа", "акци", "дефи", "nft", "web3",
    ),
    "Новости/Медиа": (
        "новост", "news", "медиа", "журнал", "репортаж", "политик", "сми", "туризм",
        "путешеств", "виз",
    ),
    "Бизнес/Стартапы": (
        "стартап", "startup", "бизнес", "предприним", "vc", "маркетинг", "продукт",
        "product manager", "менеджмент", "фаундер", "founder",
    ),
    "English": (
        "english", "английск", "ielts", "toefl", "vocabulary", "grammar", "фонетик",
    ),
    "Здоровье/Спорт": (
        "здоров", "медиц", "фитнес", "спорт", "питани", "wellness", "health", "трениров",
    ),
    "Развлечения": (
        "юмор", "мем", "кино", "сериал", "игр", "game", "музык",
    ),
}

PARENT_ML_AI: Final[str] = "ML/AI"
PARENT_IT_DEV: Final[str] = "IT/Dev"

PARENT_DOMAIN_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    PARENT_ML_AI: (
        "ml", "ai", "нейросет", "нейро", "llm", "gpt", "machine learning", "deep learning",
        "data science", "nlp", "computer vision", "искусственный интеллект", "дата сайент",
        "datascience", "recsys", "recommendation", "kaggle", "нейросет",
    ),
    PARENT_IT_DEV: (
        "разработ", "программ", "python", "javascript", "backend", "frontend", "devops",
        "docker", "kubernetes", "git", "opensource", "software", "код", "инженер", "tech",
        "айти", " it ", "tproger", "habr",
    ),
}

ML_AI_SUBCLUSTERS: Final[dict[str, tuple[str, ...]]] = {
    "Вакансии": (
        "ваканс", "jobs", "job", "hiring", "рекрут", "hr", "career fair", "оффер",
        "relocate", "релока", "удаленк", "remote", "zarubezhom", "opento", "connectable",
        "odsjobs", "ods.ai/jobs", "machinelearning jobs", "data science jobs",
    ),
    "Собеседования": (
        "собеседован", "interview", "leetcode", "вопросы с собес", "ml interview",
    ),
    "Обучение": (
        "курс", "course", "школа", "school", "обучен", "учеб", "магистрат", "stepik",
        "урок", "tutorial", "поток обуч", "academy", "talent hub", "itmo", "mlinside",
        "база ml", "учим", "образован", "stepik awards", "препод",
    ),
    "Статьи и обзоры": (
        "обзор", "стать", "article", "papers", "gonzo", "reads", "библиотек", "wiki",
        "datapedia", "переводим", "разбор", "digest", "подборка", "канал о машинном",
    ),
    "Новости": (
        "новост", "news", "ньюз", "ai news", "нейроканал", "освещаю", "новости из мира",
        "культурно освещаю",
    ),
    "Мероприятия": (
        "fest", "митап", "meetup", "конферен", "events", "datafest", "хакатон", "ods events",
        "мероприят",
    ),
    "Прод и инженерия": (
        "prod", "production", "под капотом", "engineering", "в продакшн", "wildberries",
        "wb делает", "avito tech", "mws ai", "yandex for ml", "corporate", "внедрен",
        "reliable ml", "recsys channel", "рекомендательн", "ai hub", "лаборатор",
    ),
    "Карьера и блоги": (
        "карьер", "career", "блог", "ex-", "работаю", "author", "мысли", "личный",
        "опыт", "berlin", "faang", "директор", "founder", "ceo", "commit history",
    ),
}

IT_DEV_SUBCLUSTERS: Final[dict[str, tuple[str, ...]]] = {
    "Вакансии": (
        "ваканс", "jobs", "job", "hiring", "relocate", "релока", "удаленк", "outstaff",
        "аутстафф", "фриланс", "opento", "digital ваканс",
    ),
    "Обучение": (
        "курс", "course", "школа", "обучен", "tutorial", "учеб", "книги", "books",
        "programming books", "бесплатные it книги",
    ),
    "Новости": (
        "новост", "news", "тренд", "trendwatch", "технолог", "itc", "наука и технолог",
    ),
    "Статьи и обзоры": (
        "стать", "article", "reads", "good reads", "обзор", "подборка", "находки",
        "commit history", "история моих",
    ),
    "Карьера и блоги": (
        "карьер", "career", "успех", "блог", "работаю", "разработчик в", "berlin",
        "европ", "личн",
    ),
    "Прод и инженерия": (
        "под капотом", "engineering", "инженерн", "avitotech", "митап", "github",
        "opensource",
    ),
}

_SUBCLUSTER_DEFAULT = "Общее"
_DEFAULT_THEME = "Прочее"
_WORD_RE = re.compile(r"[\wа-яё]+", re.IGNORECASE)


def _score_keywords(blob: str, tokens: set[str], keywords: tuple[str, ...]) -> int:
    score = 0
    for kw in keywords:
        kw = kw.strip().lower()
        if not kw:
            continue
        if " " in kw:
            if kw in blob:
                score += 2
        elif kw in tokens or kw in blob:
            score += 1
    return score


def _best_label(blob: str, tokens: set[str], themes: dict[str, tuple[str, ...]]) -> str | None:
    scores = {name: _score_keywords(blob, tokens, kws) for name, kws in themes.items()}
    scores = {k: v for k, v in scores.items() if v > 0}
    if not scores:
        return None
    return max(scores, key=scores.get)


def _infer_parent(blob: str, tokens: set[str]) -> str:
    ml_score = _score_keywords(blob, tokens, PARENT_DOMAIN_KEYWORDS[PARENT_ML_AI])
    it_score = _score_keywords(blob, tokens, PARENT_DOMAIN_KEYWORDS[PARENT_IT_DEV])
    tech_score = max(ml_score, it_score)

    other_scores = {
        name: _score_keywords(blob, tokens, kws) for name, kws in TOP_LEVEL_THEMES.items()
    }
    other_best = max(other_scores, key=other_scores.get) if other_scores else None
    other_score = other_scores.get(other_best, 0) if other_best else 0

    # Tech domains win when tied or stronger than generic themes (news/travel/etc.)
    if tech_score > 0 and tech_score >= other_score:
        return PARENT_ML_AI if ml_score >= it_score else PARENT_IT_DEV
    if other_best and other_score > 0:
        return other_best
    if tech_score > 0:
        return PARENT_ML_AI if ml_score >= it_score else PARENT_IT_DEV
    return _DEFAULT_THEME


def _infer_subcluster(parent: str, blob: str, tokens: set[str]) -> str:
    if parent == PARENT_ML_AI:
        sub_map = ML_AI_SUBCLUSTERS
    elif parent == PARENT_IT_DEV:
        sub_map = IT_DEV_SUBCLUSTERS
    else:
        return ""

    sub = _best_label(blob, tokens, sub_map)
    return sub or _SUBCLUSTER_DEFAULT


def infer_theme_cluster(title: str, about: str = "") -> str:
    """Return theme label, e.g. 'ML/AI — Вакансии' or 'Прочее'."""
    blob = f"{title} {about}".lower()
    tokens = set(_WORD_RE.findall(blob))

    parent = _infer_parent(blob, tokens)
    if parent in (PARENT_ML_AI, PARENT_IT_DEV):
        sub = _infer_subcluster(parent, blob, tokens)
        return f"{parent} — {sub}"
    return parent


def load_channel_themes_from_csv(csv_path: str) -> dict[str, str]:
    """Build lookup username/title -> theme_cluster from export CSV."""
    path = Path(csv_path)
    if not path.is_file():
        return {}
    mapping: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            theme = (row.get("theme_cluster") or "").strip()
            if not theme:
                continue
            username = (row.get("username") or "").strip()
            if username:
                mapping[username.lower()] = theme
                mapping[f"@{username}".lower()] = theme
            title = (row.get("title") or "").strip().lower()
            if title:
                mapping[title] = theme
    return mapping


def resolve_theme_cluster(
    title: str,
    about: str = "",
    *,
    username: str | None = None,
    csv_themes: dict[str, str] | None = None,
) -> str:
    """Prefer CSV mapping from export; fallback to keyword inference."""
    if csv_themes:
        if username:
            for key in (username.lower(), f"@{username}".lower()):
                if key in csv_themes:
                    return csv_themes[key]
        title_key = title.strip().lower()
        if title_key in csv_themes:
            return csv_themes[title_key]
    return infer_theme_cluster(title, about)
