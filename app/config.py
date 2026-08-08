"""Runtime configuration.

All values come from environment variables (optionally loaded from a local
`.env` file via python-dotenv). Nothing here is hardcoded — see
`.env.example` for the full list of variables and their defaults for local
docker-compose usage.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

# Load .env once at import time. In production, real env vars should already
# be set and this is a no-op (load_dotenv does not override existing vars).
load_dotenv()


# The answer Composer allows one structured-output repair in a run. Keep this
# constant next to configuration validation so the provider cap and the
# post-response safety budget cannot drift apart.
COMPOSER_VALIDATION_REQUEST_LIMIT = 2


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value is not None else default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value is not None else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    # --- Private runtime diagnostics ---
    # The relative default intentionally resolves in the gateway working
    # directory. Production systemd sets this to /var/log/notebook-agent.
    notebook_agent_log_dir: str = field(
        default_factory=lambda: _env("NOTEBOOK_AGENT_LOG_DIR", ".runtime/logs")
        or ".runtime/logs"
    )
    notebook_agent_log_max_bytes: int = field(
        default_factory=lambda: _env_int("NOTEBOOK_AGENT_LOG_MAX_BYTES", 10 * 1024 * 1024)
    )
    notebook_agent_log_backup_count: int = field(
        default_factory=lambda: _env_int("NOTEBOOK_AGENT_LOG_BACKUP_COUNT", 5)
    )
    notebook_agent_env: str = field(
        default_factory=lambda: _env("NOTEBOOK_AGENT_ENV", "production") or "production"
    )
    notebook_agent_log_retrieval_content: bool = field(
        default_factory=lambda: _env_bool("NOTEBOOK_AGENT_LOG_RETRIEVAL_CONTENT", False)
    )
    # --- Outbound TLS ---
    # Optional explicit CA bundle.  If unset, application composition uses
    # SSL_CERT_FILE/REQUESTS_CA_BUNDLE or certifi for the current interpreter.
    tls_ca_bundle: str | None = field(default_factory=lambda: _env("TLS_CA_BUNDLE"))

    # --- Zhipu Embedding-3 ---
    zhipu_api_key: str | None = field(default_factory=lambda: _env("ZHIPU_API_KEY"))
    embedding_model: str = field(
        default_factory=lambda: _env("EMBEDDING_MODEL", "embedding-3")
        or "embedding-3"
    )
    embedding_endpoint: str = field(
        default_factory=lambda: _env(
            "EMBEDDING_ENDPOINT",
            "https://open.bigmodel.cn/api/paas/v4/embeddings",
        )
        or "https://open.bigmodel.cn/api/paas/v4/embeddings"
    )
    embedding_dimensions: int = field(
        default_factory=lambda: _env_int("EMBEDDING_DIMENSIONS", 1536)
    )
    embedding_batch_size: int = field(
        default_factory=lambda: _env_int("EMBEDDING_BATCH_SIZE", 64)
    )

    # --- Postgres / SQLAlchemy ---
    database_url: str = field(default_factory=lambda: _build_database_url())

    # --- Redis (Celery broker + result backend) ---
    redis_url: str = field(default_factory=lambda: _build_redis_url())
    # The channel/Agent request must never wait indefinitely for the broker.
    # This is a total publish budget; the ingestion worker's retry policy is
    # intentionally separate and is not controlled by these values.
    broker_publish_timeout_seconds: float = field(
        default_factory=lambda: _env_float("BROKER_PUBLISH_TIMEOUT_SECONDS", 5.0)
    )
    broker_publish_max_retries: int = field(
        default_factory=lambda: _env_int("BROKER_PUBLISH_MAX_RETRIES", 1)
    )

    # --- MinIO (S3-compatible object storage) ---
    minio_endpoint_url: str = field(default_factory=lambda: _env("MINIO_ENDPOINT_URL", "http://localhost:9000"))
    minio_access_key: str | None = field(default_factory=lambda: _env("MINIO_ROOT_USER"))
    minio_secret_key: str | None = field(default_factory=lambda: _env("MINIO_ROOT_PASSWORD"))
    minio_bucket: str = field(default_factory=lambda: _env("MINIO_BUCKET", "kb-raw") or "kb-raw")

    # --- Knowledge retrieval Agent ---
    agent_model: str = field(
        default_factory=lambda: _env("AGENT_MODEL", "openai:gpt-5-mini")
        or "openai:gpt-5-mini"
    )
    agent_api_key: str | None = field(default_factory=lambda: _env("AGENT_API_KEY"))
    agent_base_url: str | None = field(default_factory=lambda: _env("AGENT_BASE_URL"))
    agent_timeout_seconds: float = field(
        default_factory=lambda: _env_float("AGENT_TIMEOUT_SECONDS", 45.0)
    )
    agent_tool_timeout_seconds: float = field(
        default_factory=lambda: _env_float(
            "AGENT_TOOL_TIMEOUT_SECONDS", 15.0
        )
    )
    agent_request_limit: int = field(
        default_factory=lambda: _env_int("AGENT_REQUEST_LIMIT", 8)
    )
    agent_tool_calls_limit: int = field(
        default_factory=lambda: _env_int("AGENT_TOOL_CALLS_LIMIT", 10)
    )
    agent_output_token_limit: int = field(
        default_factory=lambda: _env_int("AGENT_OUTPUT_TOKEN_LIMIT", 2000)
    )
    agent_composer_max_tokens: int = field(
        default_factory=lambda: _env_int("AGENT_COMPOSER_MAX_TOKENS", 1000)
    )
    agent_save_enabled: bool = field(
        default_factory=lambda: _env_bool("AGENT_SAVE_ENABLED", False)
    )
    # Inventory/CRUD rollout is intentionally independent from save actions.
    # Deleted-content filters remain active even when this flag is disabled.
    agent_item_management_enabled: bool = field(
        default_factory=lambda: _env_bool("AGENT_ITEM_MANAGEMENT_ENABLED", False)
    )
    trash_retention_days: int = field(
        default_factory=lambda: _env_int("TRASH_RETENTION_DAYS", 30)
    )
    trash_purge_interval_seconds: int = field(
        default_factory=lambda: _env_int("TRASH_PURGE_INTERVAL_SECONDS", 3600)
    )
    trash_purge_batch_size: int = field(
        default_factory=lambda: _env_int("TRASH_PURGE_BATCH_SIZE", 20)
    )
    trash_purge_claim_timeout_seconds: int = field(
        default_factory=lambda: _env_int("TRASH_PURGE_CLAIM_TIMEOUT_SECONDS", 1800)
    )
    trash_purge_max_duration_seconds: float = field(
        default_factory=lambda: _env_float("TRASH_PURGE_MAX_DURATION_SECONDS", 30.0)
    )
    trash_purge_object_timeout_seconds: float = field(
        default_factory=lambda: _env_float("TRASH_PURGE_OBJECT_TIMEOUT_SECONDS", 10.0)
    )
    context_max_turns: int = field(
        default_factory=lambda: _env_int("CONTEXT_MAX_TURNS", 8)
    )
    context_token_budget: int = field(
        default_factory=lambda: _env_int("CONTEXT_TOKEN_BUDGET", 6000)
    )
    channel_link_ttl_seconds: int = field(
        default_factory=lambda: _env_int("CHANNEL_LINK_TTL_SECONDS", 600)
    )
    channel_gateway_secret: str | None = field(
        default_factory=lambda: _env("CHANNEL_GATEWAY_SECRET")
    )
    channel_gateway_host: str = field(
        default_factory=lambda: _env("CHANNEL_GATEWAY_HOST", "127.0.0.1")
        or "127.0.0.1"
    )
    channel_gateway_port: int = field(
        default_factory=lambda: _env_int("CHANNEL_GATEWAY_PORT", 8765)
    )

    def __post_init__(self) -> None:
        if self.notebook_agent_env not in {"development", "production"}:
            raise ValueError("NOTEBOOK_AGENT_ENV must be development or production")
        if self.notebook_agent_log_retrieval_content and self.notebook_agent_env != "development":
            raise ValueError("retrieval content logging requires NOTEBOOK_AGENT_ENV=development")
        if self.agent_composer_max_tokens <= 0:
            raise ValueError("AGENT_COMPOSER_MAX_TOKENS must be positive")
        if self.trash_retention_days <= 0:
            raise ValueError("TRASH_RETENTION_DAYS must be positive")
        if self.trash_purge_interval_seconds <= 0:
            raise ValueError("TRASH_PURGE_INTERVAL_SECONDS must be positive")
        if self.trash_purge_batch_size <= 0 or self.trash_purge_batch_size > 100:
            raise ValueError("TRASH_PURGE_BATCH_SIZE must be between 1 and 100")
        if self.trash_purge_claim_timeout_seconds <= 0:
            raise ValueError("TRASH_PURGE_CLAIM_TIMEOUT_SECONDS must be positive")
        if self.trash_purge_max_duration_seconds <= 0:
            raise ValueError("TRASH_PURGE_MAX_DURATION_SECONDS must be positive")
        if self.trash_purge_object_timeout_seconds <= 0:
            raise ValueError("TRASH_PURGE_OBJECT_TIMEOUT_SECONDS must be positive")
        if (
            self.agent_composer_max_tokens * COMPOSER_VALIDATION_REQUEST_LIMIT
            > self.agent_output_token_limit
        ):
            raise ValueError(
                "AGENT_COMPOSER_MAX_TOKENS multiplied by the Composer request "
                "limit must not exceed AGENT_OUTPUT_TOKEN_LIMIT"
            )


def _build_database_url() -> str:
    explicit = _env("DATABASE_URL")
    if explicit:
        return explicit
    user = _env("POSTGRES_USER", "postgres")
    password = _require("POSTGRES_PASSWORD")
    host = _env("POSTGRES_HOST", "localhost")
    port = _env("POSTGRES_PORT", "5432")
    db = _env("POSTGRES_DB", "kb")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


def _build_redis_url() -> str:
    explicit = _env("REDIS_URL")
    if explicit:
        return explicit
    host = _env("REDIS_HOST", "localhost")
    port = _env("REDIS_PORT", "6379")
    db = _env("REDIS_DB", "0")
    return f"redis://{host}:{port}/{db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
