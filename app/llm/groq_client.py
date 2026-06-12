"""Groq API client (OpenAI-compatible) with rate limiting and 429 retry."""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

from app.core.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen/qwen3-32b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
REQUEST_TIMEOUT_SEC = 120

# Free tier: 6000 tokens/min. Keep a margin and reserve room for the response.
GROQ_TPM_BUDGET = 5_400
_RESPONSE_TOKENS_RESERVE = 1_200

_rate_lock = asyncio.Lock()
_last_request_at: float = 0.0
_token_window: list[tuple[float, int]] = []


def _estimate_tokens(prompt: str) -> int:
    # Russian text ≈ 2 chars/token; add reserve for the model response.
    return len(prompt) // 2 + _RESPONSE_TOKENS_RESERVE


def _min_interval_sec() -> float:
    rpm = get_settings().groq_rpm
    if rpm <= 0:
        return 0.0
    return 60.0 / rpm


async def _wait_for_rate_limit(prompt_tokens: int) -> None:
    global _last_request_at
    async with _rate_lock:
        interval = _min_interval_sec()
        now = time.monotonic()
        if interval > 0:
            wait = interval - (now - _last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)

        # Sliding-window TPM budget: wait until this request fits.
        while True:
            now = time.monotonic()
            _token_window[:] = [(ts, tok) for ts, tok in _token_window if now - ts < 60.0]
            used = sum(tok for _, tok in _token_window)
            if used + prompt_tokens <= GROQ_TPM_BUDGET or not _token_window:
                break
            oldest_ts = _token_window[0][0]
            wait = max(60.0 - (now - oldest_ts), 1.0)
            logger.info(
                "Groq TPM budget: used %s + need %s > %s, waiting %.0fs",
                used,
                prompt_tokens,
                GROQ_TPM_BUDGET,
                wait,
            )
            await asyncio.sleep(wait)

        _token_window.append((time.monotonic(), prompt_tokens))
        _last_request_at = time.monotonic()


def _retry_delay_sec(status: int, attempt: int) -> float | None:
    if status == 429:
        # TPM window resets within a minute; short retries just burn requests.
        return max(15.0 * attempt, 15.0)
    if status in (500, 502, 503, 504):
        return 2.0 ** attempt
    return None


async def call_groq(api_key: str, prompt: str, *, model: str | None = None) -> str:
    max_attempts = 4
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SEC)
    model_name = model or get_settings().groq_model or DEFAULT_MODEL
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "reasoning_effort": "none",
        "reasoning_format": "hidden",
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    prompt_tokens = _estimate_tokens(prompt)
    for attempt in range(1, max_attempts + 1):
        await _wait_for_rate_limit(prompt_tokens)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(GROQ_URL, headers=headers, json=payload) as response:
                    body = await response.json()
                    if response.status >= 400:
                        retry_after = _retry_delay_sec(response.status, attempt)
                        if retry_after is not None and attempt < max_attempts:
                            logger.warning(
                                "Groq HTTP %s, retry in %.1fs (%s/%s)",
                                response.status,
                                retry_after,
                                attempt,
                                max_attempts,
                            )
                            await asyncio.sleep(retry_after)
                            continue
                        raise RuntimeError(f"Groq HTTP {response.status}: {body}")

            choices = body.get("choices") or []
            if not choices:
                raise RuntimeError(f"Groq empty response: {body}")
            message = choices[0].get("message") or {}
            text = str(message.get("content", "")).strip()
            if not text:
                raise RuntimeError(f"Groq no text in response: {body}")
            return text
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001
            if attempt == max_attempts:
                logger.exception("Groq failed: %s", exc)
                raise
            delay = 2.0 ** attempt
            logger.warning("Groq retry %s/%s: %s", attempt, max_attempts, exc)
            await asyncio.sleep(delay)
    return ""
