import inspect
from dataclasses import replace

from pydantic_ai.models.openai import OpenAIChatModel

from app.agent.provider import build_model
from app.config import Settings
from app.ingest.tasks import create_item, ingest_url
from app.retrieval.search import bm25_search, vector_search


def test_provider_gateway_configuration_is_isolated_from_agent_contracts():
    settings = replace(
        Settings(),
        agent_model="openai:compatible-model",
        agent_api_key="test-key",
        agent_base_url="http://127.0.0.1:9999/v1",
    )

    model = build_model(settings)

    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "compatible-model"


def test_ingest_and_retrieval_require_explicit_user_id():
    for function in (create_item, ingest_url, bm25_search, vector_search):
        parameter = inspect.signature(function).parameters["user_id"]
        assert parameter.default is inspect.Parameter.empty
