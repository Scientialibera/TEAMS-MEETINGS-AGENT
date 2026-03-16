from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from src.config import get_settings
from src.graph.auth import graph_get, graph_post, graph_patch, graph_delete

logger = logging.getLogger(__name__)

_ACTIVE_SUBSCRIPTION_ID: str | None = None


def _expiry(minutes: int = 60) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime(
        "%Y-%m-%dT%H:%M:%S.0000000Z"
    )


async def ensure_transcript_subscription() -> str:
    """Create or renew the tenant-level transcript subscription.

    Resource: communications/onlineMeetings/getAllTranscripts
    """
    global _ACTIVE_SUBSCRIPTION_ID
    s = get_settings()

    if _ACTIVE_SUBSCRIPTION_ID:
        try:
            return await _renew_subscription(_ACTIVE_SUBSCRIPTION_ID)
        except Exception:
            logger.info("Subscription %s expired; creating new one.", _ACTIVE_SUBSCRIPTION_ID)
            _ACTIVE_SUBSCRIPTION_ID = None

    body = {
        "changeType": "created",
        "notificationUrl": s.webhook_url,
        "resource": "communications/onlineMeetings/getAllTranscripts",
        "expirationDateTime": _expiry(s.subscription_renewal_minutes),
        "clientState": "teams-meetings-agent",
        "lifecycleNotificationUrl": s.webhook_url,
    }

    result = await graph_post(f"{s.graph_base_url}/subscriptions", body)
    _ACTIVE_SUBSCRIPTION_ID = result.get("id")
    logger.info("Created transcript subscription: %s", _ACTIVE_SUBSCRIPTION_ID)
    return _ACTIVE_SUBSCRIPTION_ID


async def _renew_subscription(subscription_id: str) -> str:
    s = get_settings()
    body = {"expirationDateTime": _expiry(s.subscription_renewal_minutes)}
    await graph_patch(f"{s.graph_base_url}/subscriptions/{subscription_id}", body)
    logger.info("Renewed subscription: %s", subscription_id)
    return subscription_id


async def delete_transcript_subscription() -> None:
    global _ACTIVE_SUBSCRIPTION_ID
    if not _ACTIVE_SUBSCRIPTION_ID:
        return
    s = get_settings()
    try:
        await graph_delete(f"{s.graph_base_url}/subscriptions/{_ACTIVE_SUBSCRIPTION_ID}")
        logger.info("Deleted subscription: %s", _ACTIVE_SUBSCRIPTION_ID)
    except Exception:
        logger.warning("Failed to delete subscription %s", _ACTIVE_SUBSCRIPTION_ID, exc_info=True)
    finally:
        _ACTIVE_SUBSCRIPTION_ID = None
