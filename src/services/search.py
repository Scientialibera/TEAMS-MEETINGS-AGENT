from __future__ import annotations

import logging
import hashlib
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery

from src.config import get_settings

logger = logging.getLogger(__name__)

_credential = DefaultAzureCredential()


def _get_client() -> SearchClient:
    s = get_settings()
    return SearchClient(
        endpoint=s.search_endpoint,
        index_name=s.search_index,
        credential=_credential,
    )


def chunk_text(text: str, max_tokens: int = 800) -> list[str]:
    """Rough token-based chunking (1 token ~ 4 chars)."""
    max_chars = max_tokens * 4
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        # try to break at newline
        if end < len(text):
            nl = text.rfind("\n", start, end)
            if nl > start:
                end = nl + 1
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


async def index_transcript(
    *,
    meeting_id: str,
    transcript_id: str,
    meeting_subject: str,
    meeting_organizer: str,
    meeting_date: str,
    attendees: list[str],
    plain_text: str,
    summary: str,
    action_items_text: str,
    embed_fn=None,
) -> int:
    """Chunk transcript text and push to AI Search. Returns number of docs indexed."""
    s = get_settings()
    client = _get_client()
    chunks = chunk_text(plain_text)
    docs: list[dict[str, Any]] = []

    for i, chunk in enumerate(chunks):
        doc_id = hashlib.sha256(f"{transcript_id}:{i}".encode()).hexdigest()[:64]
        doc: dict[str, Any] = {
            "id": doc_id,
            "meeting_id": meeting_id,
            "transcript_id": transcript_id,
            "meeting_subject": meeting_subject,
            "meeting_organizer": meeting_organizer,
            "meeting_date": meeting_date,
            "attendees": attendees,
            "chunk_index": i,
            "chunk_text": chunk,
            "action_items": action_items_text if i == 0 else "",
            "summary": summary if i == 0 else "",
        }

        if s.search_use_vector and embed_fn:
            try:
                vector = await embed_fn(chunk)
                doc["content_vector"] = vector
            except Exception:
                logger.warning("Embedding failed for chunk %d of transcript %s", i, transcript_id)

        docs.append(doc)

    if docs:
        result = client.upload_documents(documents=docs)
        succeeded = sum(1 for r in result if r.succeeded)
        logger.info("Indexed %d/%d chunks for transcript %s", succeeded, len(docs), transcript_id)
        return succeeded
    return 0


async def search_transcripts(
    query: str,
    *,
    embed_fn=None,
    top: int = 5,
    filters: str | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search across indexed transcripts."""
    s = get_settings()
    client = _get_client()

    kwargs: dict[str, Any] = {
        "search_text": query,
        "top": top,
        "select": ["id", "meeting_id", "transcript_id", "meeting_subject",
                    "meeting_organizer", "meeting_date", "chunk_text", "summary", "action_items"],
    }

    if filters:
        kwargs["filter"] = filters

    if s.search_use_vector and embed_fn:
        try:
            vector = await embed_fn(query)
            kwargs["vector_queries"] = [
                VectorizedQuery(
                    vector=vector,
                    k_nearest_neighbors=top,
                    fields="content_vector",
                )
            ]
        except Exception:
            logger.warning("Embedding query failed, falling back to text-only search")

    results = client.search(**kwargs)
    hits: list[dict[str, Any]] = []
    for r in results:
        hits.append(dict(r))
    return hits
