from __future__ import annotations

import logging

from src.config import get_settings
from src.graph.auth import graph_get

logger = logging.getLogger(__name__)


async def resolve_user_id(upn: str) -> str | None:
    """Resolve a UPN (email) to an Entra object ID."""
    s = get_settings()
    url = f"{s.graph_base_url}/users/{upn}?$select=id,displayName,userPrincipalName"
    try:
        data = await graph_get(url)
        return data.get("id")
    except Exception:
        logger.warning("Could not resolve user: %s", upn, exc_info=True)
        return None


async def get_user_display_name(user_id: str) -> str:
    s = get_settings()
    url = f"{s.graph_base_url}/users/{user_id}?$select=displayName"
    try:
        data = await graph_get(url)
        return data.get("displayName", user_id)
    except Exception:
        return user_id
