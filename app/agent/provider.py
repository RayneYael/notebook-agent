"""Model provider selection kept separate from Agent tools and contracts."""

from __future__ import annotations

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import Settings


def build_model(settings: Settings) -> Model | str:
    """Build a direct provider or an OpenAI-compatible gateway model."""

    if settings.agent_base_url:
        model_name = settings.agent_model.removeprefix("openai:")
        return OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(
                base_url=settings.agent_base_url,
                api_key=settings.agent_api_key,
            ),
        )
    if settings.agent_model.startswith("openai:") and settings.agent_api_key:
        return OpenAIChatModel(
            settings.agent_model.removeprefix("openai:"),
            provider=OpenAIProvider(api_key=settings.agent_api_key),
        )
    return settings.agent_model
