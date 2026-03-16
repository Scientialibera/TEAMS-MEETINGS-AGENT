from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import web

from src.webhooks.validation import handle_validation

logger = logging.getLogger(__name__)

_transcript_processor = None  # set by app.py at startup


def set_transcript_processor(processor) -> None:
    global _transcript_processor
    _transcript_processor = processor


async def handle_notification(request: web.Request) -> web.Response:
    """Receive Graph change notifications for transcripts.

    Handles both:
    - Subscription validation (validationToken query param)
    - Actual change notifications (JSON body with value[])
    """
    validation_response = await handle_validation(request)
    if validation_response is not None:
        return validation_response

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    notifications = body.get("value", [])
    if not notifications:
        return web.Response(status=202)

    # Verify client state
    for notification in notifications:
        if notification.get("clientState") != "teams-meetings-agent":
            logger.warning("Notification with unexpected clientState: %s", notification.get("clientState"))
            continue

        resource = notification.get("resource", "")
        change_type = notification.get("changeType", "")
        logger.info("Change notification: type=%s resource=%s", change_type, resource)

        if change_type == "created" and "transcripts" in resource.lower():
            resource_data = notification.get("resourceData", {})
            asyncio.create_task(_dispatch_transcript(notification, resource_data))

        # Lifecycle notifications (reauthorizationRequired, subscriptionRemoved, etc.)
        lifecycle = notification.get("lifecycleEvent")
        if lifecycle == "reauthorizationRequired":
            logger.info("Reauthorization requested for subscription %s", notification.get("subscriptionId"))
            asyncio.create_task(_renew_subscription_from_notification(notification))

    return web.Response(status=202)


async def _dispatch_transcript(notification: dict, resource_data: dict) -> None:
    if _transcript_processor is None:
        logger.error("Transcript processor not configured.")
        return

    try:
        await _transcript_processor.process_transcript_notification(notification, resource_data)
    except Exception:
        logger.error("Failed to process transcript notification", exc_info=True)


async def _renew_subscription_from_notification(notification: dict) -> None:
    from src.graph.subscriptions import ensure_transcript_subscription

    try:
        await ensure_transcript_subscription()
    except Exception:
        logger.error("Failed to renew subscription from lifecycle event", exc_info=True)
