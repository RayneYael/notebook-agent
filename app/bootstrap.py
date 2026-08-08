"""Application composition root for CLI and channel gateway processes."""

from __future__ import annotations

from app.agent.actions import AgentActionServices
from app.agent.provider import build_model
from app.agent.runtime import KnowledgeAgent
from app.agent.services import KnowledgeServices
from app.agent.management import KnowledgeItemManagementService
from app.channels.service import ChannelService
from app.channels.pending_actions import PendingConfirmationService
from app.config import Settings, get_settings
from app.db import get_session_factory
from app.ingest.embed import EmbeddingProvider, ZhipuEmbedder
from app.ingest.submission import IngestSubmissionService
from app.ingest.tasks import publish_ingest_dispatch
from app.tls import TrustedCA, configure_trusted_ca


def build_embedding_provider(
    settings: Settings, *, trusted_ca: TrustedCA | None = None
) -> EmbeddingProvider | None:
    """Build the only embedding configuration used by CLI and channel requests."""

    trusted_ca = trusted_ca or configure_trusted_ca(settings.tls_ca_bundle)
    if settings.embedding_dimensions < 1:
        raise ValueError("embedding dimensions must be positive")
    if not settings.zhipu_api_key:
        return None
    return ZhipuEmbedder(
        settings.zhipu_api_key,
        model=settings.embedding_model,
        endpoint=settings.embedding_endpoint,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.embedding_batch_size,
        ssl_context=trusted_ca.ssl_context,
    )


def build_knowledge_agent(
    settings: Settings,
    *,
    session_factory=None,
) -> KnowledgeAgent:
    factory = session_factory or get_session_factory()
    trusted_ca = configure_trusted_ca(settings.tls_ca_bundle)
    embedder = build_embedding_provider(settings, trusted_ca=trusted_ca)

    def service_factory(request):
        return KnowledgeServices(request.tenant, factory, embedder=embedder)

    action_factory = None
    if settings.agent_save_enabled or settings.agent_item_management_enabled:
        action_services = AgentActionServices(
            submission=IngestSubmissionService(
                factory, publish_ingest_dispatch
            ),
            pending=PendingConfirmationService(factory),
            management=KnowledgeItemManagementService(
                factory, retention_days=settings.trash_retention_days
            ),
        )

        def action_factory(_request):
            return action_services

    # ``configure_trusted_ca`` exports the resolved bundle through the standard
    # Python TLS environment before provider construction.  Do not create a
    # per-model httpx client here: the provider owns its default client and its
    # lifecycle, while the embedding client receives the same context directly.
    return KnowledgeAgent(
        build_model(settings),
        settings,
        service_factory,
        action_factory=action_factory,
    )


def build_channel_service(settings: Settings | None = None) -> ChannelService:
    settings = settings or get_settings()
    factory = get_session_factory()
    agent = build_knowledge_agent(settings, session_factory=factory)
    return ChannelService(factory, agent, settings)


def build_mcp_server(
    settings: Settings | None = None,
    *,
    scope: str = "full",
    token: str | None = None,
):
    """Build the MCP adapter without selecting a process-wide AppUser.

    ``token`` is useful for a local stdio process whose operator has already
    selected one grant.  Streamable HTTP resolves the bearer per request in
    ``McpAuthMiddleware``; this helper never accepts an application-user id.
    """

    from app.mcp_grants import McpGrantService
    from app.mcp_server import McpToolFacade, create_mcp_server

    settings = settings or get_settings()
    factory = get_session_factory()
    grant_service = McpGrantService(factory)
    resolved = None
    if token:
        try:
            resolved = grant_service.resolve(token.strip())
        except Exception:
            raise RuntimeError("MCP token is invalid or unavailable") from None
        # A local stdio token is authoritative for discovery; do not build a
        # full mutation profile and hope invocation-time checks hide tools.
        scope = resolved.scope
    return create_mcp_server(
        scope=scope,
        facade=McpToolFacade(
            settings=settings,
            grant_service=grant_service,
            grant=resolved,
        ),
    )
