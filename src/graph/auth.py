from __future__ import annotations

import logging
from functools import lru_cache

import aiohttp
from msal import ConfidentialClientApplication

from src.config import get_settings

logger = logging.getLogger(__name__)

_GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]


@lru_cache(maxsize=1)
def _get_msal_app() -> ConfidentialClientApplication:
    s = get_settings()
    authority = f"https://login.microsoftonline.com/{s.app_tenant_id}"
    return ConfidentialClientApplication(
        client_id=s.app_id,
        client_credential=s.app_password,
        authority=authority,
    )


def get_graph_token() -> str:
    app = _get_msal_app()
    result = app.acquire_token_for_client(scopes=_GRAPH_SCOPE)
    if "access_token" in result:
        return result["access_token"]
    raise RuntimeError(f"Failed to acquire Graph token: {result.get('error_description', result)}")


async def graph_get(url: str, *, session: aiohttp.ClientSession | None = None) -> dict:
    token = get_graph_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    try:
        async with session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()
    finally:
        if own_session:
            await session.close()


async def graph_get_text(url: str, accept: str = "text/vtt") -> str:
    token = get_graph_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": accept}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.text()


async def graph_post(url: str, body: dict, *, session: aiohttp.ClientSession | None = None) -> dict:
    token = get_graph_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    try:
        async with session.post(url, headers=headers, json=body) as resp:
            resp.raise_for_status()
            return await resp.json()
    finally:
        if own_session:
            await session.close()


async def graph_patch(url: str, body: dict) -> dict:
    token = get_graph_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.patch(url, headers=headers, json=body) as resp:
            resp.raise_for_status()
            return await resp.json()


async def graph_delete(url: str) -> None:
    token = get_graph_token()
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as session:
        async with session.delete(url, headers=headers) as resp:
            resp.raise_for_status()
