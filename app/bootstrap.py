"""Application composition root for CLI and channel gateway processes."""

from __future__ import annotations

from app.agent.provider import build_model
from app.agent.runtime import KnowledgeAgent
from app.agent.services import KnowledgeServices
from app.channels.service import ChannelService
from app.config import Settings, get_settings
from app.db import get_session_factory
from app.ingest.embed import EmbeddingProvider, ZhipuEmbedder


def build_embedding_provider(settings: Settings) -> EmbeddingProvider | None:
    """Build the only embedding configuration used by CLI and channel requests."""

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
    )


def build_knowledge_agent(
    settings: Settings,
    *,
    session_factory=None,
) -> KnowledgeAgent:
    factory = session_factory or get_session_factory()
    embedder = build_embedding_provider(settings)

    def service_factory(request):
        return KnowledgeServices(request.tenant, factory, embedder=embedder)

    return KnowledgeAgent(build_model(settings), settings, service_factory)


def build_channel_service(settings: Settings | None = None) -> ChannelService:
    settings = settings or get_settings()
    factory = get_session_factory()
    agent = build_knowledge_agent(settings, session_factory=factory)
    return ChannelService(factory, agent, settings)
