from dataclasses import replace

import pytest
from pydantic_ai.models.test import TestModel

from app.agent.runtime import KnowledgeAgent, build_agent
from app.agent.services import ItemDetails
from app.agent.types import AgentRequest, Citation
from app.channels.types import TenantContext
from app.config import Settings


class FakeServices:
    def __init__(self, citations):
        self.citations = citations
        self.calls = []

    def search_segments(self, query, *, limit=6):
        self.calls.append("search_segments")
        return self.citations

    def get_neighbors(self, segment_id, *, radius=1):
        self.calls.append("get_neighbors")
        return self.citations

    def get_item(self, item_id):
        self.calls.append("get_item")
        return ItemDetails(item_id, "title", None, None, "https://example", "youtube", 60)

    def open_at(self, segment_id):
        self.calls.append("open_at")
        return self.citations[0]


def request():
    return AgentRequest(
        question="在哪里提到这个概念？",
        tenant=TenantContext(1, 1, "telegram", "bot", "user"),
        thread_db_id=1,
        thread_public_id="thread",
        message_id="message",
    )


@pytest.mark.asyncio
async def test_agent_requires_search_and_returns_only_recorded_sources():
    citation = Citation(
        item_id=2,
        segment_id=3,
        title="Only source",
        excerpt="actual evidence",
        url="https://youtu.be/video?t=42",
        start_sec=42,
    )
    settings = replace(Settings(), agent_timeout_seconds=2)
    services = FakeServices([citation])
    runtime = KnowledgeAgent(
        TestModel(call_tools="all", custom_output_text="answer [S3]"),
        settings,
        lambda _: services,
    )

    result = await runtime.run(request())

    assert result.answer.status == "ok"
    assert result.answer.citations == [citation]
    assert "https://youtu.be/video?t=42" in result.answer.text
    assert result.new_messages
    assert set(services.calls) == {
        "search_segments",
        "get_neighbors",
        "get_item",
        "open_at",
    }


@pytest.mark.asyncio
async def test_agent_rejects_model_answer_that_skips_retrieval():
    settings = replace(Settings(), agent_timeout_seconds=2)
    runtime = KnowledgeAgent(
        TestModel(call_tools=[], custom_output_text="unsupported answer"),
        settings,
        lambda _: FakeServices([]),
    )

    result = await runtime.run(request())

    assert result.answer.status == "failed"
    assert result.answer.error_code == "search_required"
    assert not result.answer.citations


@pytest.mark.asyncio
async def test_agent_empty_search_fails_closed():
    settings = replace(Settings(), agent_timeout_seconds=2)
    runtime = KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="made up"),
        settings,
        lambda _: FakeServices([]),
    )

    result = await runtime.run(request())

    assert result.answer.status == "not_found"
    assert result.answer.text == "知识库中未找到足够证据。"


def test_model_tool_schemas_never_expose_user_id():
    agent = build_agent(TestModel())
    tools = agent._function_toolset.tools

    assert set(tools) == {"search_segments", "get_neighbors", "get_item", "open_at"}
    for tool in tools.values():
        assert "user_id" not in tool.function_schema.json_schema["properties"]


@pytest.mark.asyncio
async def test_agent_rejects_missing_or_fabricated_citation_markers():
    citation = Citation(
        item_id=2,
        segment_id=3,
        title="source",
        excerpt="evidence",
        url="https://example.test",
    )
    settings = replace(Settings(), agent_timeout_seconds=2)
    for output in ("answer without marker", "answer [S999]"):
        runtime = KnowledgeAgent(
            TestModel(call_tools=["search_segments"], custom_output_text=output),
            settings,
            lambda _: FakeServices([citation]),
        )
        result = await runtime.run(request())
        assert result.answer.status == "failed"
        assert result.answer.error_code == "citation_required"


@pytest.mark.asyncio
async def test_agent_tool_error_and_request_limit_fail_closed():
    class BrokenServices(FakeServices):
        def search_segments(self, query, *, limit=6):
            raise RuntimeError("database unavailable")

    settings = replace(Settings(), agent_timeout_seconds=2)
    broken = KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="answer"),
        settings,
        lambda _: BrokenServices([]),
    )
    failed = await broken.run(request())
    assert failed.answer.status == "failed"
    assert failed.answer.error_code == "runtime_error"

    citation = Citation(
        item_id=2,
        segment_id=3,
        title="source",
        excerpt="evidence",
        url="https://example.test",
    )
    limited = KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="answer [S3]"),
        replace(settings, agent_request_limit=1),
        lambda _: FakeServices([citation]),
    )
    exhausted = await limited.run(request())
    assert exhausted.answer.status == "failed"
    assert exhausted.answer.error_code == "limit"
