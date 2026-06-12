"""Digest scheduler: night batch + morning digest."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.storage.settings import get_schedule

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_night_handler: Callable[[], Awaitable[None]] | None = None
_morning_handler: Callable[[], Awaitable[None]] | None = None


def _schedule_times() -> dict[str, int]:
    env = get_settings()
    persisted = get_schedule()
    return {
        "batch_hour": persisted.get("batch_hour", env.batch_hour),
        "batch_minute": persisted.get("batch_minute", env.batch_minute),
        "digest_hour": persisted.get("digest_hour", env.digest_hour),
        "digest_minute": persisted.get("digest_minute", env.digest_minute),
    }


def create_scheduler(
    night_batch_handler: Callable[[], Awaitable[None]],
    morning_digest_handler: Callable[[], Awaitable[None]],
) -> AsyncIOScheduler:
    global _scheduler, _night_handler, _morning_handler
    _night_handler = night_batch_handler
    _morning_handler = morning_digest_handler

    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    _scheduler = scheduler
    _register_jobs(scheduler)
    return scheduler


def _register_jobs(scheduler: AsyncIOScheduler) -> None:
    settings = get_settings()
    times = _schedule_times()

    async def _night_job() -> None:
        if _night_handler is None:
            return
        logger.info("Scheduled night batch started")
        try:
            await _night_handler()
            logger.info("Scheduled night batch finished")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Scheduled night batch failed: %s", exc)

    async def _morning_job() -> None:
        if _morning_handler is None:
            return
        logger.info("Scheduled morning digest started")
        try:
            await _morning_handler()
            logger.info("Scheduled morning digest finished")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Scheduled morning digest failed: %s", exc)

    scheduler.add_job(
        _night_job,
        CronTrigger(
            hour=times["batch_hour"],
            minute=times["batch_minute"],
            timezone=settings.timezone,
        ),
        id="night_batch_job",
        replace_existing=True,
    )
    scheduler.add_job(
        _morning_job,
        CronTrigger(
            hour=times["digest_hour"],
            minute=times["digest_minute"],
            timezone=settings.timezone,
        ),
        id="morning_digest_job",
        replace_existing=True,
    )
    logger.info(
        "Scheduler: batch at %02d:%02d, digest at %02d:%02d (%s)",
        times["batch_hour"],
        times["batch_minute"],
        times["digest_hour"],
        times["digest_minute"],
        settings.timezone,
    )


def reschedule_jobs() -> None:
    """Reload cron triggers after /set_schedule."""
    if _scheduler is None:
        return
    _register_jobs(_scheduler)
