from __future__ import annotations

from typing import Any


def build_search_results_card(query: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Adaptive Card displaying transcript search results."""
    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": f"Search Results for: \"{query}\"",
            "weight": "Bolder",
            "size": "Medium",
            "wrap": True,
        },
    ]

    if not results:
        body.append({
            "type": "TextBlock",
            "text": "No matching transcripts found.",
            "wrap": True,
            "spacing": "Medium",
        })
        return {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.5",
            "body": body,
        }

    actions: list[dict[str, Any]] = []

    for i, hit in enumerate(results[:5]):
        subject = hit.get("meeting_subject", "Unknown Meeting")
        date = hit.get("meeting_date", "")
        organizer = hit.get("meeting_organizer", "")
        snippet = hit.get("chunk_text", "")[:200]
        tid = hit.get("transcript_id", "")
        mid = hit.get("meeting_id", "")

        body.append({"type": "TextBlock", "text": "---", "spacing": "Small"})
        body.append({
            "type": "TextBlock",
            "text": f"**{i+1}. {subject}**",
            "wrap": True,
        })

        meta_parts = []
        if date:
            meta_parts.append(date[:10])
        if organizer:
            meta_parts.append(f"Organizer: {organizer}")
        if meta_parts:
            body.append({
                "type": "TextBlock",
                "text": " | ".join(meta_parts),
                "isSubtle": True,
                "spacing": "None",
            })

        if snippet:
            body.append({
                "type": "TextBlock",
                "text": f"...{snippet}...",
                "wrap": True,
                "spacing": "Small",
                "isSubtle": True,
            })

        actions.append({
            "type": "Action.Submit",
            "title": f"Chat: {subject[:30]}",
            "data": {
                "action": "select_transcript",
                "meeting_id": mid,
                "transcript_id": tid,
            },
        })

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": body,
        "actions": actions[:5],
    }
