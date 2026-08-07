import inspect
from dataclasses import replace

from pydantic_ai.models.openai import OpenAIChatModel

from app.agent.provider import build_model
from app.bootstrap import build_embedding_provider, build_knowledge_agent
from app.agent.actions import AgentActionServices
from app.channels.pending_actions import PendingConfirmationService
from app.config import Settings
from app.ingest.tasks import create_item, ingest_url
from app.ingest.submission import IngestSubmissionService
from app.retrieval.search import bm25_search, vector_search
from app.tls import TrustedCA


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


def test_query_embedding_provider_receives_the_resolved_ca_context():
    context = object()
    provider = build_embedding_provider(
        replace(Settings(), zhipu_api_key="test-key"),
        trusted_ca=TrustedCA(bundle_path="/safe/ca.pem", ssl_context=context),
    )

    assert provider is not None
    assert provider._ssl_context is context


def test_ingest_and_retrieval_require_explicit_user_id():
    for function in (create_item, ingest_url, bm25_search, vector_search):
        parameter = inspect.signature(function).parameters["user_id"]
        assert parameter.default is inspect.Parameter.empty


def test_save_enabled_composition_builds_real_action_services():
    factory = lambda: None
    agent = build_knowledge_agent(
        replace(
            Settings(),
            agent_save_enabled=True,
            zhipu_api_key=None,
        ),
        session_factory=factory,
    )

    services = agent._action_factory(None)

    assert isinstance(services, AgentActionServices)
    assert isinstance(services.submission, IngestSubmissionService)
    assert isinstance(services.pending, PendingConfirmationService)


def test_save_disabled_composition_has_no_action_factory():
    agent = build_knowledge_agent(
        replace(
            Settings(),
            agent_save_enabled=False,
            zhipu_api_key=None,
        ),
        session_factory=lambda: None,
    )

    assert agent._action_factory is None
