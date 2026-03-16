from __future__ import annotations

from typing import Any


def build_transcript_picker_card(
    transcripts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Adaptive Card listing transcripts for the user to select a chat session."""
    choices = []
    for t in transcripts:
        tid = t.get("transcript_id", t.get("id", ""))
        subject = t.get("meeting_subject", "Unknown Meeting")
        date = t.get("meeting_date", "")
        label = f"{subject} ({date[:10]})" if date else subject
        choices.append({"title": label, "value": tid})

    if not choices:
        return {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.5",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "No transcripts found. Transcripts appear here after meetings with recording enabled.",
                    "wrap": True,
                }
            ],
        }

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": "Select a Transcript",
                "weight": "Bolder",
                "size": "Medium",
            },
            {
                "type": "TextBlock",
                "text": "Choose which meeting transcript you'd like to chat about:",
                "wrap": True,
                "spacing": "Small",
            },
            {
                "type": "Input.ChoiceSet",
                "id": "selected_transcript_id",
                "style": "expanded",
                "choices": choices,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Start Chat Session",
                "data": {"action": "start_transcript_chat"},
            }
        ],
    }
