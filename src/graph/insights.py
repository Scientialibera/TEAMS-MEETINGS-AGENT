from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.config import get_settings
from src.graph.auth import graph_get

logger = logging.getLogger(__name__)


@dataclass
class MeetingInsight:
    meeting_notes: list[dict[str, Any]] = field(default_factory=list)
    action_items: list[dict[str, Any]] = field(default_factory=list)
    mention_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def summary_text(self) -> str:
        parts: list[str] = []
        for note in self.meeting_notes:
            title = note.get("title", "")
            text = note.get("text", "")
            parts.append(f"**{title}**\n{text}")
            for sub in note.get("subpoints", []):
                parts.append(f"  - {sub.get('title', '')}: {sub.get('text', '')}")
        return "\n\n".join(parts) if parts else "No meeting notes available."

    @property
    def action_items_text(self) -> str:
        if not self.action_items:
            return "No action items."
        lines = []
        for item in self.action_items:
            owner = item.get("ownerDisplayName", "Unassigned")
            lines.append(f"- **{item.get('title', '')}**: {item.get('text', '')} (Owner: {owner})")
        return "\n".join(lines)


async def get_ai_insights(user_id: str, meeting_id: str) -> MeetingInsight | None:
    """Fetch Copilot AI Insights for a meeting. Requires Copilot license on the user."""
    s = get_settings()
    url = f"{s.copilot_base_url}/users/{user_id}/onlineMeetings/{meeting_id}/aiInsights"

    try:
        data = await graph_get(url)
    except Exception:
        logger.warning("AI Insights unavailable for meeting %s (user %s)", meeting_id, user_id, exc_info=True)
        return None

    insights_list = data.get("value", [])
    if not insights_list:
        return None

    insight_id = insights_list[0].get("id")
    detail_url = f"{s.copilot_base_url}/users/{user_id}/onlineMeetings/{meeting_id}/aiInsights/{insight_id}"
    try:
        detail = await graph_get(detail_url)
    except Exception:
        logger.warning("Could not fetch AI Insight detail %s", insight_id, exc_info=True)
        return None

    viewpoint = detail.get("viewpoint", {})
    return MeetingInsight(
        meeting_notes=detail.get("meetingNotes", []),
        action_items=detail.get("actionItems", []),
        mention_events=viewpoint.get("mentionEvents", []),
    )
