from __future__ import annotations

from collections import OrderedDict
from typing import Any


class ConversationStateStore:
    """In-memory state for transcript sessions and chat history.

    Keyed by user AAD object ID. Tracks:
    - Active transcript session per user
    - Per-transcript chat history
    - Cached transcript text (LRU-bounded)
    """

    def __init__(self, max_transcripts_cached: int = 100, max_history_turns: int = 20) -> None:
        self._active_sessions: dict[str, dict[str, str]] = {}
        self._chat_histories: dict[str, list[dict[str, str]]] = {}
        self._transcript_cache: OrderedDict[str, str] = OrderedDict()
        self._max_cached = max_transcripts_cached
        self._max_turns = max_history_turns

    # -- Active transcript session -------------------------------------------

    def set_active_transcript(self, user_id: str, transcript_id: str, meeting_id: str) -> None:
        self._active_sessions[user_id] = {
            "transcript_id": transcript_id,
            "meeting_id": meeting_id,
        }

    def get_active_transcript(self, user_id: str) -> dict[str, str] | None:
        return self._active_sessions.get(user_id)

    def clear_active_transcript(self, user_id: str) -> None:
        self._active_sessions.pop(user_id, None)

    # -- Chat history --------------------------------------------------------

    def _history_key(self, user_id: str, transcript_id: str) -> str:
        return f"{user_id}:{transcript_id}"

    def get_chat_history(self, user_id: str, transcript_id: str) -> list[dict[str, str]]:
        return self._chat_histories.get(self._history_key(user_id, transcript_id), [])

    def add_chat_turn(self, user_id: str, transcript_id: str, user_msg: str, assistant_msg: str) -> None:
        key = self._history_key(user_id, transcript_id)
        history = self._chat_histories.setdefault(key, [])
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": assistant_msg})
        if len(history) > self._max_turns * 2:
            self._chat_histories[key] = history[-(self._max_turns * 2):]

    # -- Transcript text cache -----------------------------------------------

    def cache_transcript_text(self, transcript_id: str, text: str) -> None:
        self._transcript_cache[transcript_id] = text
        self._transcript_cache.move_to_end(transcript_id)
        while len(self._transcript_cache) > self._max_cached:
            self._transcript_cache.popitem(last=False)

    def get_transcript_text(self, transcript_id: str) -> str | None:
        text = self._transcript_cache.get(transcript_id)
        if text is not None:
            self._transcript_cache.move_to_end(transcript_id)
        return text
