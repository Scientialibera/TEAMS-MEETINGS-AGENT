from __future__ import annotations

import logging
from typing import Any

from src.config import get_settings
from src.graph.auth import graph_get, graph_get_text

logger = logging.getLogger(__name__)


async def get_transcript_metadata(user_id: str, meeting_id: str, transcript_id: str) -> dict[str, Any]:
    s = get_settings()
    url = (
        f"{s.graph_base_url}/users/{user_id}"
        f"/onlineMeetings/{meeting_id}/transcripts/{transcript_id}"
    )
    return await graph_get(url)


async def get_transcript_content(user_id: str, meeting_id: str, transcript_id: str) -> str:
    """Fetch the VTT transcript text."""
    s = get_settings()
    url = (
        f"{s.graph_base_url}/users/{user_id}"
        f"/onlineMeetings/{meeting_id}/transcripts/{transcript_id}/content"
    )
    return await graph_get_text(url, accept="text/vtt")


async def list_transcripts(user_id: str, meeting_id: str) -> list[dict[str, Any]]:
    s = get_settings()
    url = (
        f"{s.graph_base_url}/users/{user_id}"
        f"/onlineMeetings/{meeting_id}/transcripts"
    )
    data = await graph_get(url)
    return data.get("value", [])


async def get_meeting_by_join_url(user_id: str, join_url: str) -> dict[str, Any] | None:
    """Resolve an online meeting object from its join URL."""
    s = get_settings()
    from urllib.parse import quote

    encoded = quote(join_url, safe="")
    url = f"{s.graph_base_url}/users/{user_id}/onlineMeetings?$filter=joinWebUrl eq '{encoded}'"
    try:
        data = await graph_get(url)
        items = data.get("value", [])
        return items[0] if items else None
    except Exception:
        logger.warning("Could not resolve meeting by joinUrl for user %s", user_id, exc_info=True)
        return None


def parse_vtt_to_plain_text(vtt: str) -> str:
    """Strip VTT timing cues and tags, returning plain speaker text."""
    lines: list[str] = []
    for line in vtt.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("WEBVTT") or "-->" in stripped:
            continue
        # strip <v SpeakerName>...</v> tags but keep content
        import re
        clean = re.sub(r"<v\s+[^>]*>", "", stripped)
        clean = clean.replace("</v>", "")
        if clean:
            lines.append(clean)
    return "\n".join(lines)
