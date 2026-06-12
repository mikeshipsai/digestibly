"""Unified LLM client: Gemini primary, Groq fallback on limits."""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.llm.errors import GeminiLimitError
from app.llm.gemini_client import call_gemini
from app.llm.groq_client import call_groq

logger = logging.getLogger(__name__)

_gemini_unavailable = False


def reset_llm_provider_state() -> None:
    """Reset session flag (for tests)."""
    global _gemini_unavailable
    _gemini_unavailable = False


async def call_llm(prompt: str) -> str:
    """Call Gemini; on rate/quota limits fall back to Groq if configured."""
    global _gemini_unavailable
    settings = get_settings()

    if not _gemini_unavailable:
        try:
            return await call_gemini(settings.gemini_api_key, prompt)
        except GeminiLimitError as exc:
            _gemini_unavailable = True
            logger.warning("Gemini limit reached, switching to Groq for this run: %s", exc)
        except RuntimeError as exc:
            if _looks_like_gemini_limit(str(exc)):
                _gemini_unavailable = True
                logger.warning("Gemini limit reached, switching to Groq for this run: %s", exc)
            else:
                raise

    if not settings.groq_api_key:
        raise RuntimeError("Gemini unavailable and GROQ_API_KEY is not set")

    logger.info("LLM request via Groq (%s)", settings.groq_model)
    return await call_groq(settings.groq_api_key, prompt)


def _looks_like_gemini_limit(message: str) -> bool:
    lowered = message.lower()
    return "429" in message or "quota" in lowered or "resource_exhausted" in lowered
