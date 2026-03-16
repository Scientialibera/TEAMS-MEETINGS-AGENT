from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from redis.asyncio import Redis

from src.config import get_settings
from src.graph.calendar import get_upcoming_meetings, meeting_start_iso
from src.graph.users import resolve_user_id

logger = logging.getLogger(__name__)

_credential = DefaultAzureCredential()
_sent_reminders_fallback: set[str] = set()
_redis_client: Redis | None = None


def _reminder_cache_key(reminder_key: str) -> str:
    return f"reminder:sent:{reminder_key}"


def _get_redis_client() -> Redis | None:
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    s = get_settings()
    if not s.redis_host:
        return None

    _redis_client = Redis(
        host=s.redis_host,
        port=s.redis_port,
        password=s.redis_password or None,
        ssl=s.redis_ssl,
        decode_responses=True,
    )
    return _redis_client


async def _try_reserve_reminder(reminder_key: str) -> bool:
    s = get_settings()
    redis_client = _get_redis_client()
    if redis_client is None:
        if reminder_key in _sent_reminders_fallback:
            return False
        _sent_reminders_fallback.add(reminder_key)
        return True

    try:
        return bool(
            await redis_client.set(
                _reminder_cache_key(reminder_key),
                "1",
                ex=s.redis_reminder_ttl_seconds,
                nx=True,
            )
        )
    except Exception:
        logger.error("Redis cache unavailable while reserving reminder key", exc_info=True)
        if reminder_key in _sent_reminders_fallback:
            return False
        _sent_reminders_fallback.add(reminder_key)
        return True


async def _release_reminder(reminder_key: str) -> None:
    redis_client = _get_redis_client()
    if redis_client is None:
        _sent_reminders_fallback.discard(reminder_key)
        return
    try:
        await redis_client.delete(_reminder_cache_key(reminder_key))
    except Exception:
        logger.error("Redis cache unavailable while releasing reminder key", exc_info=True)
        _sent_reminders_fallback.discard(reminder_key)


async def load_monitored_users() -> list[dict[str, Any]]:
    s = get_settings()
    blob_svc = BlobServiceClient(account_url=s.blob_account_url, credential=_credential)
    blob = blob_svc.get_blob_client(container=s.blob_users_container, blob="monitored_users.json")
    try:
        data = blob.download_blob().readall()
        return json.loads(data)
    except Exception:
        logger.error("Failed to load monitored users from blob", exc_info=True)
        return []


async def scan_and_remind(send_reminder_fn) -> int:
    """Scan calendars for monitored users and trigger reminders.

    Args:
        send_reminder_fn: async callable(user_id, event) to send the reminder card.

    Returns:
        Number of reminders sent.
    """
    users = await load_monitored_users()
    if not users:
        return 0

    count = 0
    for user_entry in users:
        upn = user_entry.get("upn", "")
        user_id = await resolve_user_id(upn)
        if not user_id:
            continue

        meetings = await get_upcoming_meetings(user_id)
        for event in meetings:
            event_id = event.get("id", "")
            reminder_key = f"{user_id}:{event_id}"
            if not await _try_reserve_reminder(reminder_key):
                continue

            try:
                await send_reminder_fn(user_id, event)
                count += 1
            except Exception:
                await _release_reminder(reminder_key)
                logger.error("Failed to send reminder for %s / %s", upn, event.get("subject"), exc_info=True)

    return count
