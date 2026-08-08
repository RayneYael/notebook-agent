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
from urllib.parse import urlsplit

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


def _env_channels(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name)
    if value is None:
        return default
    channels = tuple(
        dict.fromkeys(part.strip().lower() for part in value.split(",") if part.strip())
    )
    unsupported = set(channels) - {"telegram", "wechat"}
    if not channels or unsupported:
        raise ValueError(f"{name} must contain only telegram and/or wechat")
    return channels


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
    # Tenant-level cost guardrails apply to both Web and channel saves.  They
    # bound durable queue work and long-term storage; per-request batch limits
    # alone are not sufficient because a caller can submit many batches.
    ingest_max_active_per_user: int = field(
        default_factory=lambda: _env_int("INGEST_MAX_ACTIVE_PER_USER", 10)
    )
    ingest_daily_new_item_limit: int = field(
        default_factory=lambda: _env_int("INGEST_DAILY_NEW_ITEM_LIMIT", 50)
    )
    ingest_max_items_per_user: int = field(
        default_factory=lambda: _env_int("INGEST_MAX_ITEMS_PER_USER", 1000)
    )
    ingest_max_active_global: int = field(
        default_factory=lambda: _env_int("INGEST_MAX_ACTIVE_GLOBAL", 100)
    )
    ingest_daily_new_item_limit_global: int = field(
        default_factory=lambda: _env_int(
            "INGEST_DAILY_NEW_ITEM_LIMIT_GLOBAL", 300
        )
    )
    ingest_daily_dispatch_limit_per_user: int = field(
        default_factory=lambda: _env_int(
            "INGEST_DAILY_DISPATCH_LIMIT_PER_USER", 100
        )
    )
    ingest_daily_dispatch_limit_global: int = field(
        default_factory=lambda: _env_int(
            "INGEST_DAILY_DISPATCH_LIMIT_GLOBAL", 1000
        )
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

    # --- MCP transport ---
    # These settings are intentionally independent from the private LangBot
    # bridge.  MCP startup never requires CHANNEL_GATEWAY_SECRET.
    mcp_host: str = field(
        default_factory=lambda: _env("MCP_HOST", "127.0.0.1") or "127.0.0.1"
    )
    mcp_port: int = field(default_factory=lambda: _env_int("MCP_PORT", 8000))
    mcp_path: str = field(
        default_factory=lambda: _env("MCP_PATH", "/mcp") or "/mcp"
    )
    mcp_url_token_mode: bool = field(
        default_factory=lambda: _env_bool("MCP_URL_TOKEN_MODE", False)
    )

    # --- Same-origin Web auth ---
    web_auth_secret: str | None = field(
        default_factory=lambda: _env("WEB_AUTH_SECRET")
    )
    web_auth_challenge_ttl_seconds: int = field(
        default_factory=lambda: _env_int("WEB_AUTH_CHALLENGE_TTL_SECONDS", 600)
    )
    web_auth_session_ttl_seconds: int = field(
        default_factory=lambda: _env_int("WEB_AUTH_SESSION_TTL_SECONDS", 2592000)
    )
    web_auth_attempt_limit: int = field(
        default_factory=lambda: _env_int("WEB_AUTH_ATTEMPT_LIMIT", 5)
    )
    web_auth_rate_window_seconds: int = field(
        default_factory=lambda: _env_int("WEB_AUTH_RATE_WINDOW_SECONDS", 60)
    )
    web_auth_rate_limit_per_requester: int = field(
        default_factory=lambda: _env_int(
            "WEB_AUTH_RATE_LIMIT_PER_REQUESTER", 5
        )
    )
    web_auth_global_rate_limit: int = field(
        default_factory=lambda: _env_int("WEB_AUTH_GLOBAL_RATE_LIMIT", 100)
    )
    web_auth_active_challenge_limit: int = field(
        default_factory=lambda: _env_int("WEB_AUTH_ACTIVE_CHALLENGE_LIMIT", 3)
    )
    web_auth_challenge_retention_seconds: int = field(
        default_factory=lambda: _env_int(
            "WEB_AUTH_CHALLENGE_RETENTION_SECONDS", 86400
        )
    )
    web_auth_session_retention_seconds: int = field(
        default_factory=lambda: _env_int(
            "WEB_AUTH_SESSION_RETENTION_SECONDS", 604800
        )
    )
    web_cookie_secure: bool = field(
        default_factory=lambda: _env_bool("WEB_COOKIE_SECURE", True)
    )
    web_origin: str | None = field(default_factory=lambda: _env("WEB_ORIGIN"))
    web_login_channels: tuple[str, ...] = field(
        default_factory=lambda: _env_channels(
            "WEB_LOGIN_CHANNELS", ("telegram", "wechat")
        )
    )
    web_host: str = field(
        default_factory=lambda: _env("WEB_HOST", "127.0.0.1") or "127.0.0.1"
    )
    web_port: int = field(
        default_factory=lambda: _env_int("WEB_PORT", 8000)
    )
    web_serve_static: bool = field(
        default_factory=lambda: _env_bool("WEB_SERVE_STATIC", True)
    )
    web_static_dir: str = field(
        default_factory=lambda: _env("WEB_STATIC_DIR", "web/dist") or "web/dist"
    )
    web_publish_budget_seconds: float = field(
        default_factory=lambda: _env_float("WEB_PUBLISH_BUDGET_SECONDS", 5.0)
    )
    web_forwarded_allow_ips: str = field(
        default_factory=lambda: _env("WEB_FORWARDED_ALLOW_IPS", "127.0.0.1")
        or "127.0.0.1"
    )

    def __post_init__(self) -> None:
        if self.notebook_agent_env not in {"development", "production"}:
            raise ValueError("NOTEBOOK_AGENT_ENV must be development or production")
        if (
            self.notebook_agent_log_retrieval_content
            and self.notebook_agent_env != "development"
        ):
            raise ValueError(
                "retrieval content logging requires NOTEBOOK_AGENT_ENV=development"
            )
        if not self.mcp_host.strip():
            raise ValueError("MCP_HOST must not be empty")
        if self.mcp_port < 1 or self.mcp_port > 65535:
            raise ValueError("MCP_PORT must be between 1 and 65535")
        if (
            not self.mcp_path.startswith("/")
            or self.mcp_path == "/"
            or "?" in self.mcp_path
            or "#" in self.mcp_path
        ):
            raise ValueError(
                "MCP_PATH must be an absolute path without query or fragment"
            )
        if self.mcp_path != "/" and self.mcp_path.endswith("/"):
            raise ValueError("MCP_PATH must not have a trailing slash")
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

    def validate_web_auth(self) -> None:
        if self.web_auth_secret is None or len(self.web_auth_secret) < 32:
            raise ValueError("WEB_AUTH_SECRET must contain at least 32 characters")
        if self.web_auth_challenge_ttl_seconds <= 0:
            raise ValueError("WEB_AUTH_CHALLENGE_TTL_SECONDS must be positive")
        if self.web_auth_session_ttl_seconds <= 0:
            raise ValueError("WEB_AUTH_SESSION_TTL_SECONDS must be positive")
        if self.web_auth_attempt_limit <= 0:
            raise ValueError("WEB_AUTH_ATTEMPT_LIMIT must be positive")
        if min(
            self.web_auth_rate_window_seconds,
            self.web_auth_rate_limit_per_requester,
            self.web_auth_global_rate_limit,
            self.web_auth_active_challenge_limit,
            self.web_auth_challenge_retention_seconds,
            self.web_auth_session_retention_seconds,
        ) <= 0:
            raise ValueError("Web auth rate and retention limits must be positive")
        if (
            self.web_auth_challenge_retention_seconds
            < self.web_auth_rate_window_seconds
        ):
            raise ValueError(
                "WEB_AUTH_CHALLENGE_RETENTION_SECONDS must cover the rate window"
            )
        if not self.web_host.strip():
            raise ValueError("WEB_HOST must not be blank")
        if not (1 <= self.web_port <= 65535):
            raise ValueError("WEB_PORT must be between 1 and 65535")
        if not self.web_static_dir.strip():
            raise ValueError("WEB_STATIC_DIR must not be blank")
        if self.web_publish_budget_seconds <= 0:
            raise ValueError("WEB_PUBLISH_BUDGET_SECONDS must be positive")
        if min(
            self.ingest_max_active_per_user,
            self.ingest_daily_new_item_limit,
            self.ingest_max_items_per_user,
            self.ingest_max_active_global,
            self.ingest_daily_new_item_limit_global,
            self.ingest_daily_dispatch_limit_per_user,
            self.ingest_daily_dispatch_limit_global,
        ) <= 0:
            raise ValueError("Ingest tenant limits must be positive")
        forwarded_sources = {
            value.strip()
            for value in self.web_forwarded_allow_ips.split(",")
            if value.strip()
        }
        if not forwarded_sources or "*" in forwarded_sources:
            raise ValueError(
                "WEB_FORWARDED_ALLOW_IPS must list explicit trusted proxies"
            )
        if self.web_origin is not None:
            origin = self.web_origin.strip()
            parsed = urlsplit(origin)
            loopback_http = (
                parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            )
            if (
                (parsed.scheme != "https" and not loopback_http)
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("WEB_ORIGIN must be HTTPS or a loopback HTTP origin")
            if origin.endswith("/"):
                raise ValueError("WEB_ORIGIN must not include a trailing slash")


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
