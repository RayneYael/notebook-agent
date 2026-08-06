"""Application composition root for CLI and channel gateway processes."""

from __future__ import annotations

from app.agent.provider import build_model
from app.agent.runtime import KnowledgeAgent
from app.agent.services import KnowledgeServices
from app.channels.service import ChannelService
from app.config import Settings, get_settings
from app.db import get_session_factory
from app.ingest.embed import ZhipuEmbedder


def build_channel_service(settings: Settings | None = None) -> ChannelService:
    settings = settings or get_settings()
    factory = get_session_factory()
    embedder = None
    if settings.zhipu_api_key:
        embedder = ZhipuEmbedder(
            settings.zhipu_api_key,
            model=settings.embedding_model,
            endpoint=settings.embedding_endpoint,
            dimensions=settings.embedding_dimensions,
            batch_size=settings.embedding_batch_size,
        )

    def service_factory(request):
        return KnowledgeServices(
            request.tenant,
            factory,
            embedder=embedder,
        )

    agent = KnowledgeAgent(build_model(settings), settings, service_factory)
    return ChannelService(factory, agent, settings)

