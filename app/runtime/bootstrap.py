"""Start bot polling and scheduled jobs."""

from __future__ import annotations

import logging

from app.core.logging import setup_logging
from app.pipeline.digest import (
    get_last_batch_time,
    get_last_digest_time,
    run_digest,
    run_digest_theme,
    run_morning_digest,
    run_night_batch,
)
from app.scheduling.scheduler import create_scheduler
from app.telegram import bot
from app.telegram.userbot import start_userbot, stop_userbot

logger = logging.getLogger(__name__)


async def start() -> None:
    setup_logging()

    await start_userbot()
    bot.init_bot()
    await bot.setup_bot_commands()
    dispatcher = bot.create_dispatcher()
    bot.configure_handlers(
        run_digest_handler=run_digest,
        last_digest_provider=get_last_digest_time,
        run_batch_handler=run_night_batch,
        last_batch_provider=get_last_batch_time,
        run_digest_theme_handler=lambda category: run_digest_theme(category),
    )

    scheduler = create_scheduler(run_night_batch, run_morning_digest)
    scheduler.start()
    logger.info("Scheduler started")

    try:
        await dispatcher.start_polling(bot.init_bot())
    finally:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
        await stop_userbot()
