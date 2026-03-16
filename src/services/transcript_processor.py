from __future__ import annotations

import logging
import re
from typing import Any

from src.config import get_settings
from src.graph.transcripts import get_transcript_content, get_transcript_metadata, parse_vtt_to_plain_text
from src.graph.insights import get_ai_insights
from src.services.search import index_transcript
from src.services.chat import embed_text, summarize_transcript

logger = logging.getLogger(__name__)

_send_summary_fn = None


def set_send_summary_fn(fn) -> None:
    global _send_summary_fn
    _send_summary_fn = fn


def _extract_ids_from_resource(resource: str) -> tuple[str | None, str | None, str | None]:
    """Parse user_id, meeting_id, and transcript_id from the notification resource string.

    Example resource paths:
      users('uid')/onlineMeetings('mid')/transcripts('tid')
      communications/onlineMeetings/getAllTranscripts
    """
    user_match = re.search(r"users\('([^']+)'\)", resource)
    meeting_match = re.search(r"onlineMeetings\('([^']+)'\)", resource)
    transcript_match = re.search(r"transcripts\('([^']+)'\)", resource)

    return (
        user_match.group(1) if user_match else None,
        meeting_match.group(1) if meeting_match else None,
        transcript_match.group(1) if transcript_match else None,
    )


async def process_transcript_notification(notification: dict, resource_data: dict) -> None:
    """Called when a transcript-available notification arrives.

    Fetches the transcript, gets AI Insights, indexes in AI Search,
    and sends a summary card to monitored users.
    """
    resource = notification.get("resource", "")
    user_id = resource_data.get("meetingOrganizerId") or None
    meeting_id = resource_data.get("meetingId") or None
    transcript_id = resource_data.get("id") or None

    if not user_id or not meeting_id:
        parsed_user, parsed_meeting, parsed_transcript = _extract_ids_from_resource(resource)
        user_id = user_id or parsed_user
        meeting_id = meeting_id or parsed_meeting
        transcript_id = transcript_id or parsed_transcript

    if not user_id or not meeting_id or not transcript_id:
        logger.warning("Incomplete transcript notification — cannot process. resource=%s", resource)
        return

    logger.info("Processing transcript: user=%s meeting=%s transcript=%s", user_id, meeting_id, transcript_id)

    # 1. Fetch transcript content (VTT)
    try:
        vtt = await get_transcript_content(user_id, meeting_id, transcript_id)
        plain_text = parse_vtt_to_plain_text(vtt)
    except Exception:
        logger.error("Failed to fetch transcript content", exc_info=True)
        return

    if not plain_text.strip():
        logger.info("Transcript is empty — skipping.")
        return

    # 2. Fetch AI Insights
    insight = await get_ai_insights(user_id, meeting_id)
    if insight:
        summary = insight.summary_text
        action_items = insight.action_items_text
    else:
        logger.info("AI Insights not available; falling back to Azure OpenAI summarization.")
        summary = await summarize_transcript(plain_text)
        action_items = ""

    # 3. Get transcript metadata for meeting details
    try:
        meta = await get_transcript_metadata(user_id, meeting_id, transcript_id)
    except Exception:
        meta = {}

    meeting_date = meta.get("createdDateTime", "")
    meeting_subject = f"Meeting {meeting_id[:12]}..."
    attendees: list[str] = []

    organizer = meta.get("meetingOrganizer", {})
    organizer_name = ""
    if organizer and organizer.get("user"):
        organizer_name = organizer["user"].get("displayName", "")

    # 4. Index in AI Search
    embed_fn = embed_text if get_settings().search_use_vector else None
    try:
        indexed = await index_transcript(
            meeting_id=meeting_id,
            transcript_id=transcript_id,
            meeting_subject=meeting_subject,
            meeting_organizer=organizer_name,
            meeting_date=meeting_date,
            attendees=attendees,
            plain_text=plain_text,
            summary=summary,
            action_items_text=action_items,
            embed_fn=embed_fn,
        )
        logger.info("Indexed %d chunks for transcript %s", indexed, transcript_id)
    except Exception:
        logger.error("Failed to index transcript", exc_info=True)

    # 5. Notify monitored users via bot
    if _send_summary_fn:
        try:
            await _send_summary_fn(
                user_id=user_id,
                meeting_id=meeting_id,
                transcript_id=transcript_id,
                meeting_subject=meeting_subject,
                summary=summary,
                action_items=action_items,
            )
        except Exception:
            logger.error("Failed to send summary card", exc_info=True)
