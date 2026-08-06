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


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value is not None else default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value is not None else default


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Settings:
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
    agent_request_limit: int = field(
        default_factory=lambda: _env_int("AGENT_REQUEST_LIMIT", 6)
    )
    agent_tool_calls_limit: int = field(
        default_factory=lambda: _env_int("AGENT_TOOL_CALLS_LIMIT", 10)
    )
    agent_output_token_limit: int = field(
        default_factory=lambda: _env_int("AGENT_OUTPUT_TOKEN_LIMIT", 2000)
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
