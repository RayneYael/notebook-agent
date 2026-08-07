from dataclasses import replace
import json
import logging

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from app.agent.runtime import KnowledgeAgent, _append_sources, build_agent
from app.agent.services import EmbeddingUnavailable, ItemDetails, RetrievalUnavailable
from app.agent.types import AgentRequest, Citation
from app.channels.types import TenantContext
from app.config import Settings
from app.diagnostics import RequestDiagnostics


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
        request_id="request-test-id",
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
        TestModel(
            call_tools=[
                "search_segments",
            ],
            custom_output_text="answer [S3]",
        ),
        settings,
        lambda _: services,
    )

    result = await runtime.run(request())

    assert result.answer.status == "ok"
    assert result.answer.citations == [citation]
    assert "https://youtu.be/video?t=42" in result.answer.text
    assert result.new_messages
    assert services.calls == ["search_segments"]


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


@pytest.mark.asyncio
async def test_runtime_records_aggregate_model_request_count_and_tool_boundaries(caplog):
    settings = replace(Settings(), agent_timeout_seconds=2)
    runtime = KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="made up"),
        settings,
        lambda _: FakeServices([]),
    )
    diagnostics = RequestDiagnostics.start("request", 1, "a" * 32)
    with caplog.at_level(logging.INFO, logger="notebook_agent.runtime"):
        await runtime.run(request(), diagnostics=diagnostics)
    payloads = [record.diagnostic_payload for record in caplog.records if hasattr(record, "diagnostic_payload")]
    model = [value for value in payloads if value.get("stage") == "model_attempt"]
    assert [value["call_index"] for value in model] == list(range(1, len(model) + 1))
    assert len(model) >= 2
    tool = [value for value in payloads if value.get("tool_name") == "search_segments"]
    assert [value["tool_outcome"] for value in tool] == ["started", "succeeded"]
    assert payloads.index(model[0]) < payloads.index(tool[0]) < payloads.index(model[1])


@pytest.mark.asyncio
async def test_runtime_records_failed_tool_boundary_without_query(caplog):
    class BrokenServices(FakeServices):
        def search_segments(self, query, *, limit=6):
            raise EmbeddingUnavailable("PRIVATE query must not be logged")

    runtime = KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="answer"),
        replace(Settings(), agent_timeout_seconds=2),
        lambda _: BrokenServices([]),
    )
    with caplog.at_level(logging.INFO, logger="notebook_agent.runtime"):
        await runtime.run(request(), diagnostics=RequestDiagnostics.start("request", 1, "b" * 32))
    payloads = [record.diagnostic_payload for record in caplog.records if hasattr(record, "diagnostic_payload")]
    tool = [value for value in payloads if value.get("tool_name") == "search_segments"]
    assert [value["tool_outcome"] for value in tool] == ["started", "failed"]
    assert "PRIVATE query" not in json.dumps(payloads)


def test_model_tool_schemas_never_expose_trusted_identifiers():
    agent = build_agent(TestModel())
    tools = agent._function_toolset.tools

    assert set(tools) == {
        "search_segments",
        "get_neighbors",
        "get_item",
        "open_at",
        "request_save_confirmation",
        "save_videos",
        "confirm_video_save",
        "clarify_save_confirmation",
        "cancel_video_save",
    }
    for tool in tools.values():
        properties = tool.function_schema.json_schema["properties"]
        assert {
            "user_id",
            "thread_id",
            "message_id",
            "request_key",
            "task_id",
        }.isdisjoint(properties)


def test_citation_equality_excludes_private_retrieval_diagnostics():
    public = Citation(
        item_id=2,
        segment_id=3,
        title="source",
        excerpt="evidence",
        url="https://example.test?t=42",
        start_sec=42,
    )
    with_score = public.model_copy()
    with_score._retrieval_score = 0.9

    assert with_score == public


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
        assert result.answer.error_code == "answer_unavailable"
        assert "[S999]" not in result.answer.text


@pytest.mark.asyncio
async def test_agent_repairs_fabricated_citation_with_a_fresh_search():
    citation = Citation(
        item_id=2,
        segment_id=3,
        title="source",
        excerpt="evidence",
        url="https://example.test",
    )
    services = FakeServices([citation])

    def model(messages, _info):
        tool_returns = [
            part
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        retry_requested = any(
            isinstance(part, RetryPromptPart)
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
        )
        if not tool_returns or retry_requested and len(tool_returns) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "search_segments",
                        json.dumps({"query": "safe retrieval"}),
                        tool_call_id=f"search-{len(tool_returns)}",
                    )
                ]
            )
        if len(tool_returns) == 1:
            return ModelResponse(parts=[TextPart("unsafe draft [S999]")])
        return ModelResponse(parts=[TextPart("repaired answer [S3]")])

    runtime = KnowledgeAgent(
        FunctionModel(model),
        replace(Settings(), agent_timeout_seconds=2),
        lambda _: services,
    )
    result = await runtime.run(request())

    assert result.answer.status == "ok"
    assert "repaired answer [S3]" in result.answer.text
    assert "S999" not in result.answer.text
    assert services.calls.count("search_segments") == 2
    assert result.new_messages == []


@pytest.mark.asyncio
async def test_retrieval_loop_converges_before_hard_limit_and_disables_parallel_calls():
    citation = Citation(
        item_id=2,
        segment_id=3,
        title="source",
        excerpt="evidence",
        url="https://example.test?t=42",
        start_sec=42,
    )
    services = FakeServices([citation])
    requests = []

    def looping_model(_messages, info):
        requests.append(info)
        visible = {tool.name for tool in info.function_tools}
        retrieval = visible & {"search_segments", "get_neighbors", "get_item", "open_at"}
        if "search_segments" in retrieval:
            return ModelResponse(parts=[ToolCallPart("search_segments", json.dumps({"query": "query"}), tool_call_id=f"search-{len(requests)}")])
        if "get_neighbors" in retrieval:
            return ModelResponse(parts=[ToolCallPart("get_neighbors", json.dumps({"segment_id": 3}), tool_call_id=f"neighbors-{len(requests)}")])
        return ModelResponse(parts=[TextPart("grounded answer [S3]")])

    result = await KnowledgeAgent(
        FunctionModel(looping_model), replace(Settings(), agent_timeout_seconds=2), lambda _: services
    ).run(request())

    assert result.answer.status == "ok"
    assert services.calls.count("search_segments") == 2
    assert services.calls.count("get_neighbors") == 3
    assert len(services.calls) == 5
    assert all(info.model_settings["parallel_tool_calls"] is False for info in requests)
    assert not ({"search_segments", "get_neighbors", "get_item", "open_at"} & {tool.name for tool in requests[-1].function_tools})


@pytest.mark.asyncio
async def test_zero_hit_retrieval_loop_returns_no_evidence_without_limit():
    services = FakeServices([])

    def looping_model(_messages, info):
        visible = {tool.name for tool in info.function_tools}
        if "search_segments" in visible:
            return ModelResponse(parts=[ToolCallPart("search_segments", json.dumps({"query": "query"}), tool_call_id=f"search-{len(services.calls)}")])
        return ModelResponse(parts=[TextPart("knowledge base has insufficient evidence")])

    result = await KnowledgeAgent(
        FunctionModel(looping_model), replace(Settings(), agent_timeout_seconds=2), lambda _: services
    ).run(request())

    assert result.answer.status == "not_found"
    assert result.answer.error_code == "no_evidence"
    assert services.calls == ["search_segments", "search_segments"]


@pytest.mark.asyncio
async def test_budget_exhaustion_reopens_only_fresh_search_for_citation_repair():
    citation = Citation(
        item_id=2,
        segment_id=3,
        title="source",
        excerpt="evidence",
        url="https://example.test?t=42",
        start_sec=42,
    )
    services = FakeServices([citation])
    requests = []

    def repair_model(messages, info):
        requests.append(info)
        visible = {tool.name for tool in info.function_tools}
        retries = any(
            isinstance(part, RetryPromptPart)
            for message in messages if isinstance(message, ModelRequest)
            for part in message.parts
        )
        if retries and services.calls.count("search_segments") == 2:
            assert visible & {"search_segments", "get_neighbors", "get_item", "open_at"} == {"search_segments"}
            return ModelResponse(parts=[ToolCallPart("search_segments", json.dumps({"query": "fresh"}), tool_call_id="repair-search")])
        if "search_segments" in visible:
            return ModelResponse(parts=[ToolCallPart("search_segments", json.dumps({"query": "query"}), tool_call_id=f"search-{len(services.calls)}")])
        if "get_neighbors" in visible:
            return ModelResponse(parts=[ToolCallPart("get_neighbors", json.dumps({"segment_id": 3}), tool_call_id=f"neighbors-{len(services.calls)}")])
        if services.calls.count("search_segments") > 2:
            return ModelResponse(parts=[TextPart("repaired answer [S3]")])
        return ModelResponse(parts=[TextPart("unsafe draft [S999]")])

    result = await KnowledgeAgent(
        FunctionModel(repair_model), replace(Settings(), agent_timeout_seconds=2), lambda _: services
    ).run(request())

    assert result.answer.status == "ok"
    assert services.calls.count("search_segments") == 3
    assert len(services.calls) == 6
    assert len(requests) <= 8
    assert result.new_messages == []


def test_multi_source_output_groups_top_five_videos_and_keeps_distant_timestamps():
    citations = [
        Citation(item_id=1, segment_id=11, title="Video one", excerpt="early evidence", url="https://example.test/one?t=10", start_sec=10),
        Citation(item_id=1, segment_id=19, title="Video one", excerpt="later evidence", url="https://example.test/one?t=900", start_sec=900),
        Citation(item_id=2, segment_id=21, title="Video two", excerpt="evidence", url="https://example.test/two?t=20", start_sec=20),
        Citation(item_id=3, segment_id=31, title="Video three", excerpt="evidence", url="https://example.test/three?t=30", start_sec=30),
        Citation(item_id=4, segment_id=41, title="Video four", excerpt="evidence", url="https://example.test/four?t=40", start_sec=40),
        Citation(item_id=5, segment_id=51, title="Video five", excerpt="evidence", url="https://example.test/five?t=50", start_sec=50),
        Citation(item_id=6, segment_id=61, title="Video six", excerpt="evidence", url="https://example.test/six?t=60", start_sec=60),
    ]

    rendered = _append_sources("answer [S11] [S19]", citations)

    assert rendered.count("- Video ") == 5
    assert rendered.count("- Video one") == 1
    assert "https://example.test/one?t=10" in rendered
    assert "https://example.test/one?t=900" in rendered
    assert "Video six" not in rendered
    assert "chapter" not in rendered.lower()


@pytest.mark.asyncio
async def test_multi_source_draft_over_five_videos_retries_with_grouped_top_five():
    citations = [
        Citation(
            item_id=index,
            segment_id=index,
            title=f"Video {index}",
            excerpt="evidence",
            url=f"https://example.test/{index}?t={index}",
            start_sec=index,
        )
        for index in range(1, 7)
    ]
    services = FakeServices(citations)

    def model(messages, info):
        has_result = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
        )
        retry = any(
            isinstance(part, RetryPromptPart)
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
        )
        if not has_result or retry and len(services.calls) == 1:
            assert {
                tool.name for tool in info.function_tools
            } & {"search_segments", "get_neighbors", "get_item", "open_at"} == {
                "search_segments"
            }
            return ModelResponse(parts=[ToolCallPart(
                "search_segments", json.dumps({"query": "ranked"}),
                tool_call_id=f"search-{len(services.calls)}",
            )])
        if len(services.calls) == 1:
            return ModelResponse(parts=[TextPart(
                "too many sources " + " ".join(f"[S{index}]" for index in range(1, 7))
            )])
        return ModelResponse(parts=[TextPart(
            "grouped sources " + " ".join(f"[S{index}]" for index in range(1, 6))
        )])

    result = await KnowledgeAgent(
        FunctionModel(model), replace(Settings(), agent_timeout_seconds=2), lambda _: services
    ).run(request())

    assert result.answer.status == "ok"
    assert services.calls == ["search_segments", "search_segments"]
    assert {citation.item_id for citation in result.answer.citations} == set(range(1, 6))


@pytest.mark.asyncio
async def test_agent_tool_error_and_request_limit_fail_closed():
    class BrokenServices(FakeServices):
        def search_segments(self, query, *, limit=6):
            raise RetrievalUnavailable("database unavailable")

    settings = replace(Settings(), agent_timeout_seconds=2)
    broken = KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="answer"),
        settings,
        lambda _: BrokenServices([]),
    )
    failed = await broken.run(request())
    assert failed.answer.status == "failed"
    assert failed.answer.error_code == "retrieval_unavailable"

    class MissingEmbeddingServices(FakeServices):
        def search_segments(self, query, *, limit=6):
            raise EmbeddingUnavailable("provider unavailable")

    unavailable = KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="answer"),
        settings,
        lambda _: MissingEmbeddingServices([]),
    )
    unavailable_result = await unavailable.run(request())
    assert unavailable_result.answer.error_code == "embedding_unavailable"

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
