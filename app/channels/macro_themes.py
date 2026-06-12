"""Seven stable macro themes for user-facing digest grouping."""

from __future__ import annotations

from typing import Any, Final

MACRO_THEMES: Final[tuple[str, ...]] = (
    "IT и разработка",
    "ML и AI",
    "Бизнес и стартапы",
    "Финансы и крипто",
    "Новости и медиа",
    "Обучение и карьера",
    "Другое",
)

DEFAULT_MACRO_THEME: Final[str] = "Другое"

_FINE_TO_MACRO: Final[dict[str, str]] = {
    # ML/AI subclusters
    "ML/AI — Вакансии": "ML и AI",
    "ML/AI — Новости": "ML и AI",
    "ML/AI — Обучение": "ML и AI",
    "ML/AI — Статьи и обзоры": "ML и AI",
    "ML/AI — Собеседования": "ML и AI",
    "ML/AI — Мероприятия": "ML и AI",
    "ML/AI — Прод и инженерия": "ML и AI",
    "ML/AI — Карьера и блоги": "ML и AI",
    "ML/AI — Общее": "ML и AI",
    # IT/Dev subclusters
    "IT/Dev — Вакансии": "IT и разработка",
    "IT/Dev — Новости": "IT и разработка",
    "IT/Dev — Обучение": "IT и разработка",
    "IT/Dev — Статьи и обзоры": "IT и разработка",
    "IT/Dev — Карьера и блоги": "IT и разработка",
    "IT/Dev — Прод и инженерия": "IT и разработка",
    "IT/Dev — Общее": "IT и разработка",
    # Top-level legacy themes
    "Крипто/Финансы": "Финансы и крипто",
    "Новости/Медиа": "Новости и медиа",
    "Бизнес/Стартапы": "Бизнес и стартапы",
    "English": "Обучение и карьера",
    "Здоровье/Спорт": "Другое",
    "Развлечения": "Другое",
    "Прочее": "Другое",
}

_KEYWORD_MACRO_HINTS: Final[tuple[tuple[str, str], ...]] = (
    ("ml", "ML и AI"),
    ("ai", "ML и AI"),
    ("нейро", "ML и AI"),
    ("data science", "ML и AI"),
    ("it/dev", "IT и разработка"),
    ("it/dev", "IT и разработка"),
    ("разработ", "IT и разработка"),
    ("программ", "IT и разработка"),
    ("devops", "IT и разработка"),
    ("крипто", "Финансы и крипто"),
    ("финанс", "Финансы и крипто"),
    ("бизнес", "Бизнес и стартапы"),
    ("стартап", "Бизнес и стартапы"),
    ("новост", "Новости и медиа"),
    ("медиа", "Новости и медиа"),
    ("english", "Обучение и карьера"),
    ("обучен", "Обучение и карьера"),
    ("карьер", "Обучение и карьера"),
    ("ваканс", "Обучение и карьера"),
)


def to_macro_theme(theme: str) -> str:
    """Map fine-grained or legacy theme label to one of seven macro themes."""
    theme = theme.strip()
    if theme in MACRO_THEMES:
        return theme
    if theme in _FINE_TO_MACRO:
        return _FINE_TO_MACRO[theme]
    lower = theme.lower()
    for hint, macro in _KEYWORD_MACRO_HINTS:
        if hint in lower:
            return macro
    return DEFAULT_MACRO_THEME


def merge_to_macro_themes(
    messages_by_category: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Collapse fine themes into macro buckets for digest TOC."""
    merged: dict[str, list[dict[str, Any]]] = {}
    for category, messages in messages_by_category.items():
        if not messages:
            continue
        macro = to_macro_theme(category)
        merged.setdefault(macro, []).extend(messages)
    return merged
