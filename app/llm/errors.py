"""LLM provider errors."""

from __future__ import annotations


class GeminiLimitError(RuntimeError):
    """Gemini rate limit or daily quota exceeded."""
