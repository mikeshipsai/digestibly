"""Normalize Telegram post text before LLM summarization."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_HASHTAG_RE = re.compile(r"(?<![\w#])#([\w\d_а-яА-ЯёЁ]{1,64})", re.UNICODE)
_MENTION_RE = re.compile(r"(?<![\w@])@([a-zA-Z\d_]{4,32})\b")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0001F1E0-\U0001F1FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U000023E9-\U000023FA"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "\U000020E3"
    "]+",
    flags=re.UNICODE,
)
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\u00ad]+")
_NOISE_PUNCT_RE = re.compile(r"([!?.,\-_=])\1{2,}")
_DECOR_LINE_RE = re.compile(r"^[\s\-_=]{3,}$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class PreprocessedPost:
    text_clean: str
    tags: tuple[str, ...]
    mentions: tuple[str, ...]


def _dedupe_preserve_order(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


def preprocess_post(raw_text: str) -> PreprocessedPost:
    text = unicodedata.normalize("NFKC", raw_text or "")
    tags = _dedupe_preserve_order(_HASHTAG_RE.findall(text))
    mentions = _dedupe_preserve_order(_MENTION_RE.findall(text))
    text = _HASHTAG_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    text = _EMOJI_RE.sub(" ", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _NOISE_PUNCT_RE.sub(r"\1", text)
    text = _DECOR_LINE_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return PreprocessedPost(text_clean=text, tags=tags, mentions=mentions)
