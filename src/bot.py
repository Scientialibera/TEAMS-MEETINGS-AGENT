from __future__ import annotations

import logging
from typing import Any

from botbuilder.core import ActivityHandler, CardFactory, TurnContext
from botbuilder.schema import Activity, ActivityTypes, Attachment

from src.cards.reminder_card import build_reminder_card
from src.cards.summary_card import build_summary_card
from src.cards.transcript_picker_card import build_transcript_picker_card
from src.cards.search_results_card import build_search_results_card
from src.services.chat import chat_about_transcript, embed_text
from src.services.search import search_transcripts
from src.state.conversation_state import ConversationStateStore

logger = logging.getLogger(__name__)


class MeetingsAgentBot(ActivityHandler):
    def __init__(self, state_store: ConversationStateStore) -> None:
        super().__init__()
        self._state = state_store
        self._conversation_refs: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Conversation reference management (for proactive messaging)
    # ------------------------------------------------------------------

    def save_conversation_reference(self, activity: Activity) -> None:
        ref = TurnContext.get_conversation_reference(activity)
        user_aad_id = activity.from_property.aad_object_id or activity.from_property.id
        if user_aad_id:
            self._conversation_refs[user_aad_id] = ref.as_dict()

    def get_conversation_reference(self, user_id: str) -> dict | None:
        return self._conversation_refs.get(user_id)

    # ------------------------------------------------------------------
    # Activity handlers
    # ------------------------------------------------------------------

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        self.save_conversation_reference(turn_context.activity)
        text = (turn_context.activity.text or "").strip()
        value = turn_context.activity.value  # from Adaptive Card submit

        if value:
            await self._handle_card_action(turn_context, value)
            return

        lower = text.lower()

        if lower.startswith("search:") or lower.startswith("search "):
            query = text.split(":", 1)[-1].strip() if ":" in text else text[7:].strip()
            await self._handle_search(turn_context, query)
        elif lower in ("transcripts", "list transcripts", "select transcript"):
            await self._handle_list_transcripts(turn_context)
        elif lower in ("help", "hi", "hello"):
            await self._send_help(turn_context)
        else:
            await self._handle_chat_message(turn_context, text)

    async def on_members_added_activity(self, members_added, turn_context: TurnContext) -> None:
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await self._send_help(turn_context)

    # ------------------------------------------------------------------
    # Card action dispatch
    # ------------------------------------------------------------------

    async def _handle_card_action(self, turn_context: TurnContext, value: dict) -> None:
        action = value.get("action", "")

        if action == "select_transcript":
            transcript_id = value.get("transcript_id", "")
            meeting_id = value.get("meeting_id", "")
            if transcript_id:
                user_id = self._get_user_id(turn_context)
                self._state.set_active_transcript(user_id, transcript_id, meeting_id)
                await turn_context.send_activity(
                    f"Transcript session started. Ask me anything about this meeting. "
                    f"Type **transcripts** to switch."
                )

        elif action == "start_transcript_chat":
            selected = value.get("selected_transcript_id", "")
            if selected:
                user_id = self._get_user_id(turn_context)
                self._state.set_active_transcript(user_id, selected, "")
                await turn_context.send_activity(
                    f"Chat session started for transcript. Ask me anything!"
                )
            else:
                await turn_context.send_activity("Please select a transcript first.")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def _handle_search(self, turn_context: TurnContext, query: str) -> None:
        if not query:
            await turn_context.send_activity("Usage: **search: your question about past meetings**")
            return

        await turn_context.send_activity("Searching transcripts...")

        embed_fn = embed_text if True else None
        results = await search_transcripts(query, embed_fn=embed_fn, top=5)
        card = build_search_results_card(query, results)
        attachment = CardFactory.adaptive_card(card)
        await turn_context.send_activity(Activity(type=ActivityTypes.message, attachments=[attachment]))

    async def _handle_list_transcripts(self, turn_context: TurnContext) -> None:
        embed_fn = embed_text
        results = await search_transcripts("*", embed_fn=None, top=20)

        seen: dict[str, dict] = {}
        for r in results:
            tid = r.get("transcript_id", "")
            if tid and tid not in seen:
                seen[tid] = r

        card = build_transcript_picker_card(list(seen.values()))
        attachment = CardFactory.adaptive_card(card)
        await turn_context.send_activity(Activity(type=ActivityTypes.message, attachments=[attachment]))

    async def _handle_chat_message(self, turn_context: TurnContext, text: str) -> None:
        user_id = self._get_user_id(turn_context)
        session = self._state.get_active_transcript(user_id)

        if not session:
            await turn_context.send_activity(
                "No active transcript session. Use one of these commands:\n\n"
                "- **search: your question** — search across all meeting transcripts\n"
                "- **transcripts** — list available transcripts to chat about\n"
                "- Or click **Chat about this transcript** on a summary card"
            )
            return

        transcript_id = session["transcript_id"]
        transcript_text = self._state.get_transcript_text(transcript_id)

        if not transcript_text:
            from src.services.search import search_transcripts as _search
            chunks = await _search(
                "*", embed_fn=None, top=50,
                filters=f"transcript_id eq '{transcript_id}'"
            )
            transcript_text = "\n".join(c.get("chunk_text", "") for c in sorted(chunks, key=lambda x: x.get("chunk_index", 0)))
            if transcript_text:
                self._state.cache_transcript_text(transcript_id, transcript_text)

        if not transcript_text:
            await turn_context.send_activity("Could not load transcript content. It may still be processing.")
            return

        history = self._state.get_chat_history(user_id, transcript_id)

        await turn_context.send_activity(Activity(type=ActivityTypes.typing))

        response = await chat_about_transcript(
            transcript_text=transcript_text,
            user_message=text,
            conversation_history=history,
        )

        self._state.add_chat_turn(user_id, transcript_id, text, response)
        await turn_context.send_activity(response)

    async def _send_help(self, turn_context: TurnContext) -> None:
        help_text = (
            "**Teams Meetings Agent**\n\n"
            "I help you stay on top of your meetings.\n\n"
            "**What I do:**\n"
            "- Send recording reminders before your meetings\n"
            "- Deliver meeting summaries and action items after transcription\n"
            "- Let you chat about specific transcripts\n"
            "- Search across all your indexed meeting transcripts\n\n"
            "**Commands:**\n"
            "- **search: your question** — find meetings by topic\n"
            "- **transcripts** — list transcripts to chat about\n"
            "- **help** — show this message\n\n"
            "You can also click buttons on the cards I send you."
        )
        await turn_context.send_activity(help_text)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_user_id(turn_context: TurnContext) -> str:
        return (
            turn_context.activity.from_property.aad_object_id
            or turn_context.activity.from_property.id
            or "unknown"
        )
