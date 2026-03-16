from __future__ import annotations

import logging
from typing import Any

from azure.identity import DefaultAzureCredential
from openai import AsyncAzureOpenAI

from src.config import get_settings

logger = logging.getLogger(__name__)

_credential = DefaultAzureCredential()
_client: AsyncAzureOpenAI | None = None


def _get_openai_client() -> AsyncAzureOpenAI:
    global _client
    if _client is None:
        s = get_settings()
        token_provider = _credential.get_token("https://cognitiveservices.azure.com/.default")
        _client = AsyncAzureOpenAI(
            azure_endpoint=s.aoai_endpoint,
            api_version=s.aoai_api_version,
            azure_ad_token=token_provider.token,
        )
    return _client


async def chat_about_transcript(
    transcript_text: str,
    user_message: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> str:
    """Send a question about a transcript to Azure OpenAI and return the response."""
    s = get_settings()
    client = _get_openai_client()

    system_prompt = (
        "You are a helpful meeting assistant. The user is asking about a specific Teams "
        "meeting transcript. Answer based solely on the transcript content provided. "
        "If the answer is not in the transcript, say so clearly.\n\n"
        f"--- TRANSCRIPT ---\n{transcript_text[:60000]}\n--- END TRANSCRIPT ---"
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    response = await client.chat.completions.create(
        model=s.aoai_chat_deployment,
        messages=messages,
        temperature=0.3,
        max_tokens=2000,
    )

    return response.choices[0].message.content or ""


async def summarize_transcript(transcript_text: str) -> str:
    """Fallback summarization when AI Insights are not available."""
    s = get_settings()
    client = _get_openai_client()

    messages = [
        {
            "role": "system",
            "content": (
                "You are a meeting summarizer. Provide a concise summary with:\n"
                "1. Key discussion points\n"
                "2. Decisions made\n"
                "3. Action items with owners (if mentioned)\n\n"
                "Format using markdown."
            ),
        },
        {"role": "user", "content": f"Summarize this transcript:\n\n{transcript_text[:60000]}"},
    ]

    response = await client.chat.completions.create(
        model=s.aoai_chat_deployment,
        messages=messages,
        temperature=0.2,
        max_tokens=2000,
    )

    return response.choices[0].message.content or ""


async def embed_text(text: str) -> list[float]:
    """Generate an embedding vector for the given text."""
    s = get_settings()
    client = _get_openai_client()

    response = await client.embeddings.create(
        model=s.aoai_embedding_deployment,
        input=text,
    )

    return response.data[0].embedding
