from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from src.config import get_settings
from src.graph.calendar import get_upcoming_meetings, meeting_start_iso
from src.graph.users import resolve_user_id

logger = logging.getLogger(__name__)

_credential = DefaultAzureCredential()
_sent_reminders: set[str] = set()


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
            if reminder_key in _sent_reminders:
                continue

            try:
                await send_reminder_fn(user_id, event)
                _sent_reminders.add(reminder_key)
                count += 1
            except Exception:
                logger.error("Failed to send reminder for %s / %s", upn, event.get("subject"), exc_info=True)

    _cleanup_old_reminders()
    return count


def _cleanup_old_reminders() -> None:
    """Prune sent-reminders set to avoid unbounded growth (keep last 5000)."""
    global _sent_reminders
    if len(_sent_reminders) > 5000:
        # keep the most recent half
        trimmed = set(list(_sent_reminders)[-2500:])
        _sent_reminders = trimmed
