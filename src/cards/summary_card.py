from __future__ import annotations

from typing import Any


def build_summary_card(
    meeting_subject: str,
    summary: str,
    action_items: str,
    meeting_id: str,
    transcript_id: str,
) -> dict[str, Any]:
    """Adaptive Card showing meeting summary + action items with chat button."""
    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": f"Meeting Summary: {meeting_subject}",
            "weight": "Bolder",
            "size": "Medium",
            "wrap": True,
        },
        {"type": "TextBlock", "text": "---", "spacing": "Small"},
        {
            "type": "TextBlock",
            "text": "Summary",
            "weight": "Bolder",
            "spacing": "Medium",
        },
        {
            "type": "TextBlock",
            "text": summary[:2000] if summary else "No summary available.",
            "wrap": True,
        },
    ]

    if action_items and action_items != "No action items.":
        body.extend([
            {"type": "TextBlock", "text": "---", "spacing": "Small"},
            {
                "type": "TextBlock",
                "text": "Action Items",
                "weight": "Bolder",
            },
            {
                "type": "TextBlock",
                "text": action_items[:2000],
                "wrap": True,
            },
        ])

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": body,
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Chat about this transcript",
                "data": {
                    "action": "select_transcript",
                    "meeting_id": meeting_id,
                    "transcript_id": transcript_id,
                },
            },
        ],
    }
