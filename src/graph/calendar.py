from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from src.config import get_settings
from src.graph.auth import graph_get

logger = logging.getLogger(__name__)


async def get_upcoming_meetings(user_id: str, window_minutes: int | None = None) -> list[dict[str, Any]]:
    """Return calendar events in the next *window_minutes* that are online Teams meetings."""
    s = get_settings()
    window = window_minutes or s.reminder_window_minutes
    now = datetime.now(timezone.utc)
    end = now + timedelta(minutes=window)

    start_str = now.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    end_str = end.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")

    url = (
        f"{s.graph_base_url}/users/{user_id}/calendarView"
        f"?startDateTime={start_str}&endDateTime={end_str}"
        f"&$select=id,subject,start,end,organizer,attendees,isOnlineMeeting,onlineMeeting"
        f"&$top=50"
    )

    try:
        data = await graph_get(url)
    except Exception:
        logger.error("Failed to fetch calendar for user %s", user_id, exc_info=True)
        return []

    meetings: list[dict[str, Any]] = []
    for event in data.get("value", []):
        if not event.get("isOnlineMeeting"):
            continue
        meetings.append(event)

    return meetings


def extract_join_url(event: dict) -> str | None:
    online = event.get("onlineMeeting") or {}
    return online.get("joinUrl")


def meeting_start_iso(event: dict) -> str:
    return event.get("start", {}).get("dateTime", "")
