from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger(__name__)


async def handle_validation(request: web.Request) -> web.Response:
    """Handle the Graph subscription validation handshake.

    Graph sends POST with ?validationToken=... on subscription creation.
    We must return the token as plain text with 200 OK within 10 seconds.
    """
    token = request.query.get("validationToken")
    if token:
        logger.info("Subscription validation handshake received.")
        return web.Response(text=token, content_type="text/plain", status=200)
    return None
