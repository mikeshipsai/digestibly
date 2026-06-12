"""Shared Gemini API client with rate limiting and 429 retry."""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

from app.core.config import get_settings
from app.llm.errors import GeminiLimitError

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL_NAME}:generateContent"
)
REQUEST_TIMEOUT_SEC = 120

_rate_lock = asyncio.Lock()
_last_request_at: float = 0.0


def _min_interval_sec() -> float:
    rpm = get_settings().gemini_rpm
    if rpm <= 0:
        return 0.0
    return 60.0 / rpm


async def _wait_for_rate_limit() -> None:
    global _last_request_at
    interval = _min_interval_sec()
    if interval <= 0:
        return
    async with _rate_lock:
        now = time.monotonic()
        wait = interval - (now - _last_request_at)
        if wait > 0:
            logger.debug("Gemini rate limit: sleeping %.1fs", wait)
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()


def _is_daily_quota_exhausted(body: dict) -> bool:
    details = body.get("error", {}).get("details") or []
    for item in details:
        if not item.get("@type", "").endswith("QuotaFailure"):
            continue
        for violation in item.get("violations") or []:
            quota_id = str(violation.get("quotaId", ""))
            if "PerDay" in quota_id or "PerDay" in str(violation.get("quotaMetric", "")):
                return True
    message = str(body.get("error", {}).get("message", ""))
    return "PerDay" in message or "quota exceeded" in message.lower()


def _retry_delay_sec(status: int, body: dict, attempt: int) -> float | None:
    if status == 429:
        if _is_daily_quota_exhausted(body):
            return None
        details = body.get("error", {}).get("details") or []
        for item in details:
            if item.get("@type", "").endswith("RetryInfo"):
                raw = str(item.get("retryDelay", "")).rstrip("s")
                try:
                    return max(float(raw), 1.0)
                except ValueError:
                    pass
        return max(2.0 ** attempt, 15.0)
    if status in (500, 502, 503, 504):
        return 2.0 ** attempt
    return None


async def call_gemini(api_key: str, prompt: str) -> str:
    max_attempts = 6
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SEC)
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    for attempt in range(1, max_attempts + 1):
        await _wait_for_rate_limit()
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    GEMINI_URL,
                    params={"key": api_key},
                    json=payload,
                ) as response:
                    body = await response.json()
                    if response.status >= 400:
                        if response.status == 429 and _is_daily_quota_exhausted(body):
                            raise GeminiLimitError(f"Gemini daily quota exceeded: {body}")
                        retry_after = _retry_delay_sec(response.status, body, attempt)
                        if retry_after is not None and attempt < max_attempts:
                            logger.warning(
                                "Gemini HTTP %s, retry in %.1fs (%s/%s)",
                                response.status,
                                retry_after,
                                attempt,
                                max_attempts,
                            )
                            await asyncio.sleep(retry_after)
                            continue
                        if response.status == 429:
                            raise GeminiLimitError(f"Gemini HTTP 429: {body}")
                        raise RuntimeError(f"Gemini HTTP {response.status}: {body}")
            candidates = body.get("candidates") or []
            if not candidates:
                raise RuntimeError(f"Gemini empty response: {body}")
            parts = candidates[0].get("content", {}).get("parts") or []
            text = "".join(str(p.get("text", "")) for p in parts).strip()
            if not text:
                raise RuntimeError(f"Gemini no text in response: {body}")
            return text
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001
            if attempt == max_attempts:
                logger.exception("Gemini failed: %s", exc)
                raise
            delay = 2.0 ** attempt
            logger.warning("Gemini retry %s/%s: %s", attempt, max_attempts, exc)
            await asyncio.sleep(delay)
    return ""
