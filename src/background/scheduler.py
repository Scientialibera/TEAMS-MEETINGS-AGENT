from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import get_settings
from src.graph.subscriptions import ensure_transcript_subscription
from src.services.reminder import scan_and_remind

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _reminder_tick(send_reminder_fn) -> None:
    try:
        count = await scan_and_remind(send_reminder_fn)
        if count:
            logger.info("Sent %d recording reminders.", count)
    except Exception:
        logger.error("Reminder scan failed", exc_info=True)


async def _subscription_tick() -> None:
    try:
        await ensure_transcript_subscription()
    except Exception:
        logger.error("Subscription renewal failed", exc_info=True)


def start_scheduler(send_reminder_fn) -> AsyncIOScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    s = get_settings()
    _scheduler = AsyncIOScheduler()

    _scheduler.add_job(
        _reminder_tick,
        "interval",
        minutes=s.scheduler_interval_minutes,
        args=[send_reminder_fn],
        id="reminder_scan",
        replace_existing=True,
        max_instances=1,
    )

    _scheduler.add_job(
        _subscription_tick,
        "interval",
        minutes=s.subscription_renewal_minutes,
        id="subscription_renewal",
        replace_existing=True,
        max_instances=1,
    )

    _scheduler.start()
    logger.info(
        "Scheduler started: reminders every %d min, subscription renewal every %d min.",
        s.scheduler_interval_minutes,
        s.subscription_renewal_minutes,
    )

    # Fire initial subscription creation
    asyncio.ensure_future(_subscription_tick())

    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped.")
