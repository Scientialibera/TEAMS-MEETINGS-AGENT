from __future__ import annotations

from typing import Any


def build_reminder_card(meeting_subject: str, start_time: str) -> dict[str, Any]:
    """Adaptive Card reminding user to start recording."""
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "ColumnSet",
                "columns": [
                    {
                        "type": "Column",
                        "width": "auto",
                        "items": [
                            {
                                "type": "Image",
                                "url": "https://img.icons8.com/fluency/48/video-call.png",
                                "size": "Small",
                            }
                        ],
                    },
                    {
                        "type": "Column",
                        "width": "stretch",
                        "items": [
                            {
                                "type": "TextBlock",
                                "text": "Recording Reminder",
                                "weight": "Bolder",
                                "size": "Medium",
                            },
                            {
                                "type": "TextBlock",
                                "text": f"**{meeting_subject}** starts at {start_time}",
                                "wrap": True,
                                "spacing": "Small",
                            },
                        ],
                    },
                ],
            },
            {
                "type": "TextBlock",
                "text": "Don't forget to **start the recording** and **enable transcription** when you join!",
                "wrap": True,
                "spacing": "Medium",
            },
        ],
    }
