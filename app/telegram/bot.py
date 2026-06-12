"""Aiogram bot for personal digest (owner only)."""

from __future__ import annotations

import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.core.config import get_settings
from app.pipeline.format import (
    digest_target_date,
    format_category_digest,
    format_digest_toc,
)
from app.pipeline.types import PostSummary
from app.scheduling.scheduler import reschedule_jobs
from app.storage.settings import get_schedule, is_onboarded, set_onboarded, set_schedule
from app.storage.themes import (
    create_theme,
    list_channel_overrides,
    list_custom_themes,
    mute_channel,
    set_channel_override,
    unmute_channel,
)

logger = logging.getLogger(__name__)

_router = Router()
_bot: Optional[Bot] = None
_run_digest_handler: Optional[Callable[[], Awaitable[None]]] = None
_run_batch_handler: Optional[Callable[[], Awaitable[None]]] = None
_run_digest_theme_handler: Optional[Callable[[str], Awaitable[None]]] = None
_last_digest_provider: Optional[Callable[[], Optional[datetime]]] = None
_last_batch_provider: Optional[Callable[[], Optional[datetime]]] = None

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_CACHE_TTL_SEC = 86_400
_EXPAND_PREFIX = "exp:"
_ONBOARD_PREFIX = "ob:"


@dataclass
class _DigestExpandCache:
    categories: list[str]
    summaries: dict[str, list[PostSummary]]
    digest_date: date
    created_at: float


_digest_cache: dict[str, _DigestExpandCache] = {}
_await_custom_time: set[int] = set()

_ONBOARDING_TIMES: tuple[tuple[str, int, int], ...] = (
    ("08:00", 8, 0),
    ("09:00", 9, 0),
    ("10:00", 10, 0),
)


def _is_owner(message: Message) -> bool:
    return message.chat.id == get_settings().owner_chat_id


def _is_owner_callback(callback: CallbackQuery) -> bool:
    if callback.message is None:
        return False
    return callback.message.chat.id == get_settings().owner_chat_id


def configure_handlers(
    run_digest_handler: Callable[[], Awaitable[None]],
    last_digest_provider: Callable[[], Optional[datetime]],
    *,
    run_batch_handler: Callable[[], Awaitable[None]] | None = None,
    last_batch_provider: Callable[[], Optional[datetime]] | None = None,
    run_digest_theme_handler: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    global _run_digest_handler, _last_digest_provider, _run_batch_handler, _last_batch_provider
    global _run_digest_theme_handler
    _run_digest_handler = run_digest_handler
    _last_digest_provider = last_digest_provider
    _run_batch_handler = run_batch_handler
    _last_batch_provider = last_batch_provider
    _run_digest_theme_handler = run_digest_theme_handler


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(_router)
    return dispatcher


def init_bot() -> Bot:
    global _bot
    if _bot is None:
        settings = get_settings()
        _bot = Bot(token=settings.bot_token)
    return _bot


def _prune_digest_cache() -> None:
    now = time.time()
    expired = [key for key, entry in _digest_cache.items() if now - entry.created_at > _CACHE_TTL_SEC]
    for key in expired:
        del _digest_cache[key]


def clear_digest_cache() -> None:
    _digest_cache.clear()


def _store_digest_cache(
    summaries_by_category: dict[str, list[PostSummary]],
    digest_date: date,
) -> str:
    categories = [c for c in sorted(summaries_by_category) if summaries_by_category[c]]
    token = secrets.token_hex(4)
    _digest_cache[token] = _DigestExpandCache(
        categories=categories,
        summaries=summaries_by_category,
        digest_date=digest_date,
        created_at=time.time(),
    )
    _prune_digest_cache()
    return token


def _button_label(category: str, count: int) -> str:
    label = f"📂 {category} ({count})"
    if len(label) > 64:
        return f"{label[:61]}..."
    return label


def _onboarding_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for label, hour, minute in _ONBOARDING_TIMES:
        row.append(
            InlineKeyboardButton(
                text=f"🕘 {label}",
                callback_data=f"{_ONBOARD_PREFIX}time:{hour:02d}:{minute:02d}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✏️ Другое время", callback_data=f"{_ONBOARD_PREFIX}custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_toc_keyboard(
    token: str,
    summaries_by_category: dict[str, list[PostSummary]],
) -> InlineKeyboardMarkup:
    categories = [c for c in sorted(summaries_by_category) if summaries_by_category[c]]
    rows: list[list[InlineKeyboardButton]] = []
    for idx, category in enumerate(categories):
        count = len(summaries_by_category[category])
        rows.append(
            [
                InlineKeyboardButton(
                    text=_button_label(category, count),
                    callback_data=f"{_EXPAND_PREFIX}{token}:{idx}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _split_digest_text(text: str, max_length: int = 4096) -> list[str]:
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_length:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(paragraph) <= max_length:
            current = paragraph
            continue
        words = paragraph.split()
        piece = ""
        for word in words:
            tentative = f"{piece} {word}".strip()
            if len(tentative) <= max_length:
                piece = tentative
            else:
                if piece:
                    chunks.append(piece)
                piece = word
        if piece:
            current = piece
    if current:
        chunks.append(current)
    return chunks


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


async def _send_text(
    chat_id: int,
    text: str,
    *,
    disable_notification: bool = False,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    bot_instance = init_bot()
    chunks = _split_digest_text(text)
    for idx, chunk in enumerate(chunks):
        markup = reply_markup if idx == len(chunks) - 1 else None
        try:
            await bot_instance.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
                disable_notification=disable_notification,
                reply_markup=markup,
            )
        except TelegramBadRequest as exc:
            logger.warning("HTML parsing failed, sending plain text: %s", exc)
            await bot_instance.send_message(
                chat_id=chat_id,
                text=_strip_html(chunk),
                parse_mode=None,
                disable_notification=disable_notification,
                reply_markup=markup,
            )


async def send_digest(digest_text: str, chat_id: int) -> None:
    await _send_text(chat_id, digest_text)


async def send_digest_by_category(
    summaries_by_category: dict[str, list[PostSummary]],
    chat_id: int,
) -> None:
    """Send TOC with inline buttons; themes expand on click."""
    settings = get_settings()
    digest_date = digest_target_date(settings.timezone)
    categories = [c for c in sorted(summaries_by_category) if summaries_by_category[c]]
    if not categories:
        await send_digest("За вчера новых постов не найдено.", chat_id)
        return

    token = _store_digest_cache(summaries_by_category, digest_date)
    text = format_digest_toc(digest_date, summaries_by_category)
    keyboard = _build_toc_keyboard(token, summaries_by_category)
    await _send_text(chat_id, text, reply_markup=keyboard)


async def send_single_category_digest(
    category: str,
    items: list[PostSummary],
    chat_id: int,
) -> None:
    """Send one theme digest directly (for /digest_theme)."""
    settings = get_settings()
    digest_date = digest_target_date(settings.timezone)
    text = format_category_digest(category, items, digest_date=digest_date)
    if text:
        await _send_text(chat_id, text)


def _parse_time(value: str) -> tuple[int, int]:
    match = _TIME_RE.match(value.strip())
    if not match:
        raise ValueError("Формат времени: ЧЧ:ММ, например 09:00")
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Некорректное время")
    return hour, minute


def _format_db_locked_error() -> str:
    return (
        "Сессия Telethon занята. Убедитесь, что запущен только один бот "
        "(make bot). Остановите лишние процессы и повторите."
    )


def _format_pipeline_error(exc: Exception) -> str:
    text = str(exc)
    if "database is locked" in text.lower():
        return _format_db_locked_error()
    return text


async def _run_digest_silent() -> None:
    if _run_digest_handler is None:
        raise RuntimeError("Обработчик дайджеста не настроен.")
    await _run_digest_handler()


async def _run_batch_silent() -> None:
    if _run_batch_handler is None:
        raise RuntimeError("Обработчик batch не настроен.")
    await _run_batch_handler()


def _onboarding_welcome_text() -> str:
    return (
        "Собираю посты из всех ваших Telegram-каналов "
        "и присылаю лучшее за день.\n\n"
        "Выберите время ежедневного дайджеста:"
    )


def _onboarding_done_text(hour: int, minute: int) -> str:
    return (
        f"Готово! Каждый день в {hour:02d}:{minute:02d} пришлю дайджест.\n\n"
        "Нажмите тему в оглавлении, чтобы развернуть посты.\n"
        "Чтобы скрыть канал: /mute @channel"
    )


def _ready_text() -> str:
    schedule = get_schedule()
    return (
        f"Дайджест приходит каждый день в "
        f"{schedule['digest_hour']:02d}:{schedule['digest_minute']:02d}.\n\n"
        "Чтобы скрыть канал: /mute @channel\n"
        "Чтобы изменить время: /start"
    )


async def _finish_onboarding(message: Message, hour: int, minute: int) -> None:
    set_schedule(digest_hour=hour, digest_minute=minute)
    set_onboarded(complete=True)
    reschedule_jobs()
    await message.answer(_onboarding_done_text(hour, minute), parse_mode=None)


@_router.message(Command("start"))
async def start_command(message: Message) -> None:
    if not _is_owner(message):
        await message.answer("Бот настроен для личного использования.", parse_mode=None)
        return
    if not is_onboarded():
        await message.answer(
            _onboarding_welcome_text(),
            parse_mode=None,
            reply_markup=_onboarding_keyboard(),
        )
        return
    await message.answer(
        _ready_text(),
        parse_mode=None,
        reply_markup=_onboarding_keyboard(),
    )


@_router.message(Command("help"))
async def help_command(message: Message) -> None:
    if not _is_owner(message):
        return
    await message.answer(
        "Каждый день вы получаете дайджест с саммари постов по темам.\n\n"
        "/start — настроить время\n"
        "/mute @channel — скрыть канал из дайджеста",
        parse_mode=None,
    )


@_router.message(Command("mute"))
async def mute_command(message: Message) -> None:
    if not _is_owner(message):
        return
    raw = (message.text or "").replace("/mute", "", 1).strip()
    if not raw:
        await message.answer("Использование: /mute @channel", parse_mode=None)
        return
    channel_part = raw.split()[0]
    if not channel_part.startswith("@"):
        channel_part = f"@{channel_part.lstrip('@')}"
    try:
        added = mute_channel(channel_part)
        if added:
            await message.answer(f"Канал {channel_part} скрыт из дайджеста.", parse_mode=None)
        else:
            await message.answer(f"Канал {channel_part} уже скрыт.", parse_mode=None)
    except ValueError as exc:
        await message.answer(str(exc), parse_mode=None)


@_router.message(Command("unmute"))
async def unmute_command(message: Message) -> None:
    if not _is_owner(message):
        return
    raw = (message.text or "").replace("/unmute", "", 1).strip()
    if not raw:
        await message.answer("Использование: /unmute @channel", parse_mode=None)
        return
    channel_part = raw.split()[0]
    if not channel_part.startswith("@"):
        channel_part = f"@{channel_part.lstrip('@')}"
    removed = unmute_channel(channel_part)
    if removed:
        await message.answer(f"Канал {channel_part} снова в дайджесте.", parse_mode=None)
    else:
        await message.answer(f"Канал {channel_part} не был скрыт.", parse_mode=None)


@_router.message(F.text.regexp(_TIME_RE))
async def custom_time_message(message: Message) -> None:
    if not _is_owner(message):
        return
    if message.chat.id not in _await_custom_time:
        return
    _await_custom_time.discard(message.chat.id)
    try:
        hour, minute = _parse_time(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc), parse_mode=None)
        return
    await _finish_onboarding(message, hour, minute)


@_router.message(Command("digest"))
async def digest_command(message: Message) -> None:
    if not _is_owner(message):
        return
    try:
        await _run_digest_silent()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Manual digest failed: %s", exc)
        await message.answer(f"Ошибка: {_format_pipeline_error(exc)}", parse_mode=None)


@_router.message(Command("digest_theme"))
async def digest_theme_command(message: Message) -> None:
    if not _is_owner(message):
        return
    category = (message.text or "").replace("/digest_theme", "", 1).strip()
    if not category:
        return
    if _run_digest_theme_handler is None:
        return
    try:
        await _run_digest_theme_handler(category)
    except ValueError as exc:
        await message.answer(str(exc), parse_mode=None)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Theme digest failed: %s", exc)
        await message.answer(f"Ошибка: {_format_pipeline_error(exc)}", parse_mode=None)


@_router.message(Command("batch"))
async def batch_command(message: Message) -> None:
    if not _is_owner(message):
        return
    try:
        await _run_batch_silent()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Manual batch failed: %s", exc)
        await message.answer(f"Ошибка: {_format_pipeline_error(exc)}", parse_mode=None)


@_router.message(Command("set_schedule"))
async def set_schedule_command(message: Message) -> None:
    if not _is_owner(message):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        return
    kind = parts[1].strip().lower()
    try:
        hour, minute = _parse_time(parts[2])
    except ValueError as exc:
        await message.answer(str(exc), parse_mode=None)
        return

    if kind == "digest":
        schedule = set_schedule(digest_hour=hour, digest_minute=minute)
    elif kind == "batch":
        schedule = set_schedule(batch_hour=hour, batch_minute=minute)
    else:
        return

    reschedule_jobs()
    await message.answer(
        f"Расписание обновлено.\n"
        f"Дайджест: {schedule['digest_hour']:02d}:{schedule['digest_minute']:02d}",
        parse_mode=None,
    )


@_router.message(Command("create_theme"))
async def create_theme_command(message: Message) -> None:
    if not _is_owner(message):
        return
    name = (message.text or "").replace("/create_theme", "", 1).strip()
    if not name:
        return
    try:
        created = create_theme(name)
        if created:
            await message.answer(f"Тема «{name}» создана.", parse_mode=None)
    except ValueError:
        pass


@_router.message(Command("move"))
async def move_command(message: Message) -> None:
    if not _is_owner(message):
        return
    raw = (message.text or "").replace("/move", "", 1).strip()
    if not raw or " " not in raw:
        return
    channel_part, theme = raw.split(maxsplit=1)
    channel_part = channel_part.strip()
    theme = theme.strip()
    if not channel_part.startswith("@"):
        channel_part = f"@{channel_part.lstrip('@')}"
    try:
        set_channel_override(channel_part, theme)
        await message.answer(f"Канал {channel_part} → «{theme}»", parse_mode=None)
    except ValueError:
        pass


@_router.message(Command("themes"))
async def themes_command(message: Message) -> None:
    if not _is_owner(message):
        return
    custom = list_custom_themes()
    overrides = list_channel_overrides()
    lines = ["Личные темы:", ", ".join(custom) if custom else "—"]
    lines.append("Переопределения:")
    if overrides:
        for ch, theme in sorted(overrides.items()):
            lines.append(f"• {ch} → {theme}")
    else:
        lines.append("—")
    await message.answer("\n".join(lines), parse_mode=None)


@_router.message(Command("status"))
async def status_command(message: Message) -> None:
    if not _is_owner(message):
        return
    schedule = get_schedule()
    settings = get_settings()
    last_digest = _last_digest_provider() if _last_digest_provider else None
    last_batch = _last_batch_provider() if _last_batch_provider else None
    digest_text = last_digest.strftime("%Y-%m-%d %H:%M:%S") if last_digest else "—"
    batch_text = last_batch.strftime("%Y-%m-%d %H:%M:%S") if last_batch else "—"
    await message.answer(
        f"Batch: {batch_text}\n"
        f"Дайджест: {digest_text}\n"
        f"Расписание: {schedule['digest_hour']:02d}:{schedule['digest_minute']:02d} "
        f"({settings.timezone})",
        parse_mode=None,
    )


@_router.callback_query(F.data.startswith(_EXPAND_PREFIX))
async def expand_theme_callback(callback: CallbackQuery) -> None:
    if not _is_owner_callback(callback):
        await callback.answer()
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return

    payload = callback.data[len(_EXPAND_PREFIX) :]
    try:
        token, idx_raw = payload.rsplit(":", 1)
        idx = int(idx_raw)
    except ValueError:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return

    entry = _digest_cache.get(token)
    if entry is None:
        await callback.answer("Дайджест устарел. Запустите /digest снова.", show_alert=True)
        return
    if idx < 0 or idx >= len(entry.categories):
        await callback.answer("Тема не найдена", show_alert=True)
        return

    category = entry.categories[idx]
    items = entry.summaries.get(category, [])
    if not items:
        await callback.answer("В теме нет постов", show_alert=True)
        return

    text = format_category_digest(category, items, digest_date=entry.digest_date)
    await callback.answer()
    await _send_text(callback.message.chat.id, text, disable_notification=True)


@_router.callback_query(F.data.startswith(_ONBOARD_PREFIX))
async def onboarding_callback(callback: CallbackQuery) -> None:
    if not _is_owner_callback(callback):
        await callback.answer()
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return

    action = callback.data[len(_ONBOARD_PREFIX) :]
    chat_id = callback.message.chat.id

    if action == "custom":
        _await_custom_time.add(chat_id)
        await callback.answer()
        await callback.message.answer(
            "Отправьте время в формате ЧЧ:ММ, например 09:30",
            parse_mode=None,
        )
        return

    if action.startswith("time:"):
        try:
            _, hour_raw, minute_raw = action.split(":")
            hour, minute = int(hour_raw), int(minute_raw)
        except ValueError:
            await callback.answer("Некорректное время", show_alert=True)
            return
        await callback.answer()
        set_schedule(digest_hour=hour, digest_minute=minute)
        set_onboarded(complete=True)
        reschedule_jobs()
        await callback.message.answer(_onboarding_done_text(hour, minute), parse_mode=None)
        return

    await callback.answer()
