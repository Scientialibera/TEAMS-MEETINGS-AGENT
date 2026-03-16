from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int = 0) -> int:
    raw = os.environ.get(key)
    return int(raw) if raw else default


def _env_bool(key: str, default: bool = False) -> bool:
    return _env(key, str(default)).lower() in ("true", "1", "yes")


@dataclass(frozen=True)
class Settings:
    # Bot identity
    app_id: str = field(default_factory=lambda: _env("MICROSOFT_APP_ID"))
    app_password: str = field(default_factory=lambda: _env("MICROSOFT_APP_PASSWORD"))
    app_tenant_id: str = field(default_factory=lambda: _env("MICROSOFT_APP_TENANT_ID"))
    app_type: str = field(default_factory=lambda: _env("MICROSOFT_APP_TYPE", "SingleTenant"))

    # Blob storage
    blob_account_url: str = field(default_factory=lambda: _env("BLOB_ACCOUNT_URL"))
    blob_users_container: str = field(default_factory=lambda: _env("BLOB_USERS_CONTAINER", "monitored-users"))
    blob_state_container: str = field(default_factory=lambda: _env("BLOB_STATE_CONTAINER", "bot-state"))

    # Azure OpenAI
    aoai_endpoint: str = field(default_factory=lambda: _env("AOAI_ENDPOINT"))
    aoai_api_version: str = field(default_factory=lambda: _env("AOAI_API_VERSION", "2024-12-01-preview"))
    aoai_chat_deployment: str = field(default_factory=lambda: _env("AOAI_CHAT_DEPLOYMENT"))
    aoai_embedding_deployment: str = field(default_factory=lambda: _env("AOAI_EMBEDDING_DEPLOYMENT"))

    # AI Search
    search_endpoint: str = field(default_factory=lambda: _env("SEARCH_ENDPOINT"))
    search_index: str = field(default_factory=lambda: _env("SEARCH_INDEX", "transcripts-index"))
    search_use_vector: bool = field(default_factory=lambda: _env_bool("SEARCH_USE_VECTOR", True))
    search_embedding_dimensions: int = field(default_factory=lambda: _env_int("SEARCH_EMBEDDING_DIMENSIONS", 3072))

    # Graph
    graph_api_version: str = field(default_factory=lambda: _env("GRAPH_API_VERSION", "v1.0"))
    reminder_window_minutes: int = field(default_factory=lambda: _env_int("REMINDER_WINDOW_MINUTES", 15))
    scheduler_interval_minutes: int = field(default_factory=lambda: _env_int("SCHEDULER_INTERVAL_MINUTES", 5))
    subscription_renewal_minutes: int = field(default_factory=lambda: _env_int("SUBSCRIPTION_RENEWAL_MINUTES", 50))
    webhook_url: str = field(default_factory=lambda: _env("WEBHOOK_URL"))

    # Server
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))

    @property
    def graph_base_url(self) -> str:
        return f"https://graph.microsoft.com/{self.graph_api_version}"

    @property
    def copilot_base_url(self) -> str:
        return f"https://graph.microsoft.com/{self.graph_api_version}/copilot"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
