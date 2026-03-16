from __future__ import annotations

import logging
import sys

from aiohttp import web
from botbuilder.core import BotFrameworkAdapterSettings, BotFrameworkAdapter, TurnContext
from botbuilder.schema import Activity, ActivityTypes

from src.config import get_settings
from src.bot import MeetingsAgentBot
from src.cards.reminder_card import build_reminder_card
from src.cards.summary_card import build_summary_card
from src.graph.calendar import meeting_start_iso
from src.state.conversation_state import ConversationStateStore
from src.webhooks.notification_handler import handle_notification, set_transcript_processor
from src.services.transcript_processor import set_send_summary_fn
from src.background.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _create_adapter() -> BotFrameworkAdapter:
    s = get_settings()
    settings = BotFrameworkAdapterSettings(
        app_id=s.app_id,
        app_password=s.app_password,
    )
    adapter = BotFrameworkAdapter(settings)

    async def on_error(context: TurnContext, error: Exception):
        logger.error("Bot encountered error: %s", error, exc_info=True)
        await context.send_activity("Sorry, something went wrong.")

    adapter.on_turn_error = on_error
    return adapter


# Global instances
_state_store = ConversationStateStore()
_bot = MeetingsAgentBot(_state_store)
_adapter = _create_adapter()


# --------------------------------------------------------------------------
# Route handlers
# --------------------------------------------------------------------------

async def _handle_messages(request: web.Request) -> web.Response:
    """Bot Framework messages endpoint: /api/messages"""
    if "application/json" not in (request.content_type or ""):
        return web.Response(status=415)

    body = await request.json()
    activity = Activity().deserialize(body)
    auth_header = request.headers.get("Authorization", "")

    response = await _adapter.process_activity(activity, auth_header, _bot.on_turn)
    if response:
        return web.json_response(data=response.body, status=response.status)
    return web.Response(status=201)


async def _handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "healthy"})


# --------------------------------------------------------------------------
# Proactive messaging helpers
# --------------------------------------------------------------------------

async def _send_proactive_reminder(user_id: str, event: dict) -> None:
    """Send a recording reminder card to a user proactively."""
    ref = _bot.get_conversation_reference(user_id)
    if not ref:
        logger.warning("No conversation reference for user %s — cannot send reminder.", user_id)
        return

    subject = event.get("subject", "Upcoming Meeting")
    start = meeting_start_iso(event)

    card = build_reminder_card(subject, start)

    async def _callback(turn_context: TurnContext):
        from botbuilder.core import CardFactory
        attachment = CardFactory.adaptive_card(card)
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, attachments=[attachment])
        )

    await _adapter.continue_conversation(ref, _callback, _bot._state)


async def _send_proactive_summary(
    user_id: str,
    meeting_id: str,
    transcript_id: str,
    meeting_subject: str,
    summary: str,
    action_items: str,
) -> None:
    """Send a meeting summary card to a user proactively."""
    ref = _bot.get_conversation_reference(user_id)
    if not ref:
        logger.warning("No conversation reference for user %s — cannot send summary.", user_id)
        return

    card = build_summary_card(meeting_subject, summary, action_items, meeting_id, transcript_id)

    async def _callback(turn_context: TurnContext):
        from botbuilder.core import CardFactory
        attachment = CardFactory.adaptive_card(card)
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, attachments=[attachment])
        )

    await _adapter.continue_conversation(ref, _callback, _bot._state)


# --------------------------------------------------------------------------
# App lifecycle
# --------------------------------------------------------------------------

async def _on_startup(app: web.Application) -> None:
    from src.services import transcript_processor
    set_transcript_processor(transcript_processor)
    set_send_summary_fn(_send_proactive_summary)
    start_scheduler(_send_proactive_reminder)
    logger.info("Application started.")


async def _on_shutdown(app: web.Application) -> None:
    stop_scheduler()
    logger.info("Application shutting down.")


def init_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/messages", _handle_messages)
    app.router.add_post("/api/notifications", handle_notification)
    app.router.add_get("/api/health", _handle_health)
    app.on_startup.append(_on_startup)
    app.on_shutdown.append(_on_shutdown)
    return app


if __name__ == "__main__":
    s = get_settings()
    web.run_app(init_app(), host="0.0.0.0", port=s.port)
