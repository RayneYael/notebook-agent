import asyncio
from dataclasses import replace
import json
import logging

import pytest
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage

from app.agent.runtime import (
    KnowledgeAgent,
    _append_sources,
    _compressed_citations,
    build_agent,
)
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


def composer_for(*segment_ids: int) -> TestModel:
    return TestModel(
        call_tools=[],
        custom_output_text=json.dumps({
            "sections": [
                {
                    "text": "根据知识库证据的总结。",
                    "citation_ids": list(segment_ids),
                }
            ]
        }),
    )


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
        composer_model=composer_for(3),
    )

    result = await runtime.run(request())

    assert result.answer.status == "ok"
    assert result.answer.citations == [citation]
    assert "https://youtu.be/video?t=42" in result.answer.text
    assert len(result.new_messages) == 2
    assert all(
        not isinstance(part, ToolReturnPart)
        for message in result.new_messages
        if isinstance(message, ModelRequest)
        for part in message.parts
    )
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
async def test_invalid_composer_drafts_retry_once_then_use_evidence_fallback():
    citations = [Citation(
        item_id=2,
        segment_id=3,
        title="source",
        excerpt="long evidence " * 40,
        url="https://example.test",
    ), Citation(
        item_id=2,
        segment_id=4,
        title="source",
        excerpt="another long evidence " * 40,
        url="https://example.test/other",
    )]
    composer_requests = []

    def invalid_composer(_messages, info):
        composer_requests.append(info)
        assert info.output_tools == []
        return ModelResponse(
            parts=[
                TextPart(json.dumps({
                    "sections": [{"text": "untrusted", "citation_ids": [999]}]
                }))
            ]
        )

    services = FakeServices(citations)
    runtime = KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="stop"),
        replace(Settings(), agent_timeout_seconds=2),
        lambda _: services,
        composer_model=FunctionModel(invalid_composer),
    )
    result = await runtime.run(request())

    assert result.answer.status == "ok"
    assert result.answer.error_code is None
    assert result.answer.text.startswith("自动总结未完成")
    assert "[S999]" not in result.answer.text
    assert services.calls == ["search_segments"]
    assert len(composer_requests) == 2


@pytest.mark.asyncio
async def test_composer_repairs_citation_against_same_allow_list_without_search():
    citation = Citation(
        item_id=2,
        segment_id=3,
        title="source",
        excerpt="evidence",
        url="https://example.test",
    )
    services = FakeServices([citation])

    composer_calls = []

    def composer(_messages, info):
        composer_calls.append(info)
        assert info.output_tools == []
        assert info.model_settings["max_tokens"] == 1000
        assert "extra_body" not in info.model_settings
        ids = [999] if len(composer_calls) == 1 else [3]
        return ModelResponse(
            parts=[
                TextPart(json.dumps({
                    "sections": [{"text": "repaired answer", "citation_ids": ids}]
                }))
            ]
        )

    runtime = KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="retrieval stop"),
        replace(Settings(), agent_timeout_seconds=2),
        lambda _: services,
        composer_model=FunctionModel(composer),
    )
    result = await runtime.run(request())

    assert result.answer.status == "ok"
    assert "repaired answer [S3]" in result.answer.text
    assert "S999" not in result.answer.text
    assert services.calls == ["search_segments"]
    assert len(composer_calls) == 2
    assert len(result.new_messages) == 2


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
async def test_provider_batch_executes_one_backend_retrieval_per_model_step():
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

    def batched_model(messages, info):
        requests.append(info)
        returns = [
            part
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if not returns:
            return ModelResponse(
                parts=[
                    ToolCallPart("search_segments", json.dumps({"query": "one"}), tool_call_id="search-one"),
                    ToolCallPart("search_segments", json.dumps({"query": "two"}), tool_call_id="search-two"),
                ],
                usage=RequestUsage(output_tokens=700),
            )
        if len(returns) == 2:
            assert [part.content["status"] for part in returns] == ["ok", "skipped"]
            assert returns[1].content["reason"] == "same_model_step"
            return ModelResponse(
                parts=[
                    ToolCallPart("get_neighbors", json.dumps({"segment_id": 3}), tool_call_id="neighbors-one"),
                    ToolCallPart("get_neighbors", json.dumps({"segment_id": 3}), tool_call_id="neighbors-two"),
                    ToolCallPart("get_item", json.dumps({"item_id": 2}), tool_call_id="item-three"),
                ],
                usage=RequestUsage(output_tokens=700),
            )
        assert [part.content["status"] for part in returns[-3:]] == [
            "ok", "skipped", "skipped",
        ]
        return ModelResponse(parts=[TextPart("retrieval stop")], usage=RequestUsage(output_tokens=666))

    result = await KnowledgeAgent(
        FunctionModel(batched_model),
        replace(Settings(), agent_timeout_seconds=2),
        lambda _: services,
        composer_model=composer_for(3),
    ).run(request())

    assert result.answer.status == "ok"
    assert "根据知识库证据的总结" in result.answer.text
    assert not result.answer.text.startswith("自动总结未完成")
    assert services.calls == ["search_segments", "get_neighbors"]
    assert all(info.model_settings["parallel_tool_calls"] is False for info in requests)
    assert all("max_tokens" not in info.model_settings for info in requests)
    assert all("thinking" not in info.model_settings for info in requests)
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_composer_output_limit_uses_ok_evidence_fallback_with_answer_diagnostics(caplog):
    citation = Citation(
        item_id=2,
        segment_id=3,
        title="source",
        excerpt="evidence",
        url="https://example.test?t=42",
        start_sec=42,
    )

    composer_calls = 0

    def token_limited_composer(_messages, info):
        nonlocal composer_calls
        composer_calls += 1
        assert info.output_tools == []
        return ModelResponse(
            parts=[
                TextPart(json.dumps({
                    "sections": [{"text": "draft", "citation_ids": [3]}]
                }))
            ],
            usage=RequestUsage(output_tokens=2001),
        )

    diagnostics = RequestDiagnostics.start("request", 1, "c" * 32)
    with caplog.at_level(logging.INFO, logger="notebook_agent.runtime"):
        result = await KnowledgeAgent(
            TestModel(call_tools=["search_segments"], custom_output_text="retrieval stop"),
            replace(Settings(), agent_timeout_seconds=2),
            lambda _: FakeServices([citation]),
            composer_model=FunctionModel(token_limited_composer),
        ).run(request(), diagnostics=diagnostics)

    payloads = [record.diagnostic_payload for record in caplog.records if hasattr(record, "diagnostic_payload")]
    answer_limit = [
        value for value in payloads
        if value.get("agent_phase") == "answer" and value.get("limit_kind") == "output_tokens"
    ]
    assert result.answer.status == "ok"
    assert result.answer.text.startswith("自动总结未完成")
    assert "检索步骤已达到上限" not in result.answer.text
    assert answer_limit[-1]["limit_value"] == 2000
    assert answer_limit[-1]["used_value"] == 2001
    assert composer_calls == 1
    assert not any(
        value.get("stage") == "context_compressed" for value in payloads
    )


def test_compressed_citations_preserve_item_coverage_then_retrieval_order():
    citations = [
        Citation(
            item_id=item_id,
            segment_id=segment_id,
            title=f"source {item_id}",
            excerpt="evidence " * 50,
            url=f"https://example.test/{segment_id}",
        )
        for item_id, segment_id in [
            (1, 11), (1, 12), (2, 21), (2, 22), (3, 31),
            (3, 32), (4, 41), (4, 42), (5, 51), (5, 52),
        ]
    ]
    original_excerpts = [citation.excerpt for citation in citations]

    compressed = _compressed_citations(citations)

    assert [citation.segment_id for citation in compressed] == [
        11, 21, 31, 41, 51, 12, 22, 32,
    ]
    assert len({citation.segment_id for citation in compressed}) == 8
    assert {citation.item_id for citation in compressed} == {1, 2, 3, 4, 5}
    assert [citation.excerpt for citation in citations] == original_excerpts


def compression_test_citations() -> list[Citation]:
    return [
        Citation(
            item_id=((index - 1) % 5) + 1,
            segment_id=index,
            title=f"source {index}",
            excerpt=f"evidence-{index} " * 50,
            url=f"https://example.test/{index}",
        )
        for index in range(1, 11)
    ]


@pytest.mark.asyncio
async def test_composer_output_limit_compresses_once_and_recovers(caplog):
    citations = compression_test_citations()
    citations[0] = citations[0].model_copy(
        update={"excerpt": "x" * 180 + "TRUNCATED-CONTEXT-SENTINEL"}
    )
    rendered_prompts: list[str] = []

    def composer(messages, info):
        rendered_prompts.append(
            ModelMessagesTypeAdapter.dump_json(messages).decode()
        )
        assert info.model_settings["max_tokens"] == 1000
        response = ModelResponse(parts=[TextPart(json.dumps({
            "sections": [{"text": "compressed answer", "citation_ids": [1]}]
        }))])
        if len(rendered_prompts) == 1:
            response.usage = RequestUsage(output_tokens=2001)
        return response

    diagnostics = RequestDiagnostics.start("request", 1, "f" * 32)
    with caplog.at_level(logging.INFO, logger="notebook_agent.runtime"):
        result = await KnowledgeAgent(
            TestModel(call_tools=["search_segments"], custom_output_text="stop"),
            replace(Settings(), agent_timeout_seconds=2),
            lambda _: FakeServices(citations),
            composer_model=FunctionModel(composer),
        ).run(request(), diagnostics=diagnostics)

    payloads = [
        record.diagnostic_payload
        for record in caplog.records
        if hasattr(record, "diagnostic_payload")
    ]
    compressed = [
        value for value in payloads if value.get("stage") == "context_compressed"
    ]
    terminal = [
        value for value in payloads
        if value.get("stage") == "agent_failed"
        and value.get("agent_phase") == "answer"
    ]
    assert result.answer.status == "ok"
    assert "compressed answer [S1]" in result.answer.text
    assert not result.answer.text.startswith("自动总结未完成")
    assert len(rendered_prompts) == 2
    assert rendered_prompts[0].count("ID ") == 10
    assert rendered_prompts[1].count("ID ") == 8
    assert "TRUNCATED-CONTEXT-SENTINEL" in rendered_prompts[0]
    assert "TRUNCATED-CONTEXT-SENTINEL" not in rendered_prompts[1]
    assert compressed[0]["projected_value"] == 10
    assert compressed[0]["result_count"] == 8
    assert compressed[0]["limit_kind"] == "output_tokens"
    assert not terminal


@pytest.mark.asyncio
async def test_compressed_allow_list_rejects_dropped_segment_before_repair():
    citations = compression_test_citations()
    calls = 0

    def composer(_messages, _info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[TextPart(json.dumps({
                    "sections": [{"text": "full draft", "citation_ids": [1]}]
                }))],
                usage=RequestUsage(output_tokens=2001),
            )
        citation_id = 9 if calls == 2 else 1
        return ModelResponse(parts=[TextPart(json.dumps({
            "sections": [{
                "text": "compressed repaired",
                "citation_ids": [citation_id],
            }]
        }))])

    result = await KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="stop"),
        replace(Settings(), agent_timeout_seconds=2),
        lambda _: FakeServices(citations),
        composer_model=FunctionModel(composer),
    ).run(request())

    assert calls == 3
    assert "compressed repaired [S1]" in result.answer.text
    assert "S9" not in result.answer.text


@pytest.mark.asyncio
async def test_compression_attempts_share_one_answer_timeout():
    citations = compression_test_citations()
    calls = 0
    compressed_attempt_cancelled = False

    async def composer(_messages, _info):
        nonlocal calls, compressed_attempt_cancelled
        calls += 1
        call_index = calls
        try:
            # Either attempt would fit inside a freshly reset 300 ms timeout,
            # but together they cannot fit inside the one shared deadline.
            await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            if call_index == 2:
                compressed_attempt_cancelled = True
            raise
        return ModelResponse(
            parts=[TextPart(json.dumps({
                "sections": [{"text": "too late", "citation_ids": [1]}]
            }))],
            usage=RequestUsage(output_tokens=2001 if call_index == 1 else 1),
        )

    result = await KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="stop"),
        replace(Settings(), agent_timeout_seconds=0.3),
        lambda _: FakeServices(citations),
        composer_model=FunctionModel(composer),
    ).run(request())

    assert calls == 2
    assert compressed_attempt_cancelled is True
    assert result.answer.text.startswith("自动总结未完成")
    assert "too late" not in result.answer.text


@pytest.mark.asyncio
async def test_composer_second_output_limit_uses_original_evidence_fallback(caplog):
    citations = compression_test_citations()
    calls = 0

    def composer(_messages, _info):
        nonlocal calls
        calls += 1
        return ModelResponse(
            parts=[TextPart(json.dumps({
                "sections": [{"text": "discarded", "citation_ids": [1]}]
            }))],
            usage=RequestUsage(output_tokens=2001),
        )

    with caplog.at_level(logging.INFO, logger="notebook_agent.runtime"):
        result = await KnowledgeAgent(
            TestModel(call_tools=["search_segments"], custom_output_text="stop"),
            replace(Settings(), agent_timeout_seconds=2),
            lambda _: FakeServices(citations),
            composer_model=FunctionModel(composer),
        ).run(
            request(),
            diagnostics=RequestDiagnostics.start("request", 1, "1" * 32),
        )

    payloads = [
        record.diagnostic_payload
        for record in caplog.records
        if hasattr(record, "diagnostic_payload")
    ]
    assert calls == 2
    assert result.answer.text.startswith("自动总结未完成")
    assert result.answer.citations == citations
    assert "discarded" not in result.answer.text
    assert sum(value.get("stage") == "context_compressed" for value in payloads) == 1
    assert sum(
        value.get("stage") == "agent_failed"
        and value.get("agent_phase") == "answer"
        for value in payloads
    ) == 1


@pytest.mark.asyncio
async def test_composer_length_exhaustion_uses_captured_finish_reason_for_compression():
    citations = compression_test_citations()
    calls = 0

    def composer(_messages, _info):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return ModelResponse(
                parts=[TextPart('{"sections":')],
                finish_reason="length",
            )
        return ModelResponse(parts=[TextPart(json.dumps({
            "sections": [{"text": "recovered after cutoff", "citation_ids": [1]}]
        }))])

    result = await KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="stop"),
        replace(Settings(), agent_timeout_seconds=2),
        lambda _: FakeServices(citations),
        composer_model=FunctionModel(composer),
    ).run(request())

    assert calls == 3
    assert "recovered after cutoff [S1]" in result.answer.text
    assert not result.answer.text.startswith("自动总结未完成")


@pytest.mark.asyncio
async def test_valid_but_length_marked_composer_response_is_still_compressed():
    citations = compression_test_citations()
    calls = 0

    def composer(_messages, _info):
        nonlocal calls
        calls += 1
        return ModelResponse(
            parts=[TextPart(json.dumps({
                "sections": [{
                    "text": "possibly truncated" if calls == 1 else "complete",
                    "citation_ids": [1],
                }]
            }))],
            finish_reason="length" if calls == 1 else "stop",
        )

    result = await KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="stop"),
        replace(Settings(), agent_timeout_seconds=2),
        lambda _: FakeServices(citations),
        composer_model=FunctionModel(composer),
    ).run(request())

    assert calls == 2
    assert "complete [S1]" in result.answer.text
    assert "possibly truncated" not in result.answer.text
    assert not result.answer.text.startswith("自动总结未完成")


@pytest.mark.asyncio
async def test_composer_provider_failure_discards_draft_and_returns_evidence():
    citation = Citation(
        item_id=2,
        segment_id=3,
        title="source",
        excerpt="evidence",
        url="https://example.test",
    )

    def broken_composer(_messages, _info):
        raise RuntimeError("private provider error")

    result = await KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="retrieval stop"),
        replace(Settings(), agent_timeout_seconds=2),
        lambda _: FakeServices([citation]),
        composer_model=FunctionModel(broken_composer),
    ).run(request())

    assert result.answer.status == "ok"
    assert result.answer.text.startswith("自动总结未完成")
    assert "private provider error" not in result.answer.text
    assert len(result.new_messages) == 2


@pytest.mark.asyncio
async def test_retrieval_http_error_logs_safe_status_without_body(caplog):
    body_sentinel = "PRIVATE-retrieval-http-body"

    def unavailable_model(_messages, _info):
        raise ModelHTTPError(422, "test-model", body=body_sentinel)

    diagnostics = RequestDiagnostics.start("request", 1, "d" * 32)
    with caplog.at_level(logging.INFO, logger="notebook_agent.runtime"):
        result = await KnowledgeAgent(
            FunctionModel(unavailable_model),
            replace(Settings(), agent_timeout_seconds=2),
            lambda _: FakeServices([]),
        ).run(request(), diagnostics=diagnostics)

    payloads = [record.diagnostic_payload for record in caplog.records if hasattr(record, "diagnostic_payload")]
    failure = next(value for value in payloads if value.get("error_class") == "ModelHTTPError")
    assert result.answer.status == "failed"
    assert result.answer.error_code == "runtime_error"
    assert failure["agent_phase"] == "retrieval"
    assert failure["http_status"] == 422
    assert body_sentinel not in json.dumps(payloads)


@pytest.mark.asyncio
async def test_composer_http_error_logs_safe_status_and_uses_evidence_fallback(caplog):
    citation = Citation(
        item_id=2,
        segment_id=3,
        title="source",
        excerpt="evidence",
        url="https://example.test",
    )
    body_sentinel = "PRIVATE-composer-http-body"

    def unavailable_composer(_messages, _info):
        raise ModelHTTPError(503, "test-model", body=body_sentinel)

    diagnostics = RequestDiagnostics.start("request", 1, "e" * 32)
    with caplog.at_level(logging.INFO, logger="notebook_agent.runtime"):
        result = await KnowledgeAgent(
            TestModel(call_tools=["search_segments"], custom_output_text="retrieval stop"),
            replace(Settings(), agent_timeout_seconds=2),
            lambda _: FakeServices([citation]),
            composer_model=FunctionModel(unavailable_composer),
        ).run(request(), diagnostics=diagnostics)

    payloads = [record.diagnostic_payload for record in caplog.records if hasattr(record, "diagnostic_payload")]
    failure = next(value for value in payloads if value.get("error_class") == "ModelHTTPError")
    assert result.answer.status == "ok"
    assert result.answer.error_code is None
    assert result.answer.text.startswith("自动总结未完成")
    assert failure["agent_phase"] == "answer"
    assert failure["http_status"] == 503
    assert body_sentinel not in json.dumps(payloads)


@pytest.mark.asyncio
async def test_composer_timeout_discards_draft_and_returns_evidence():
    citation = Citation(
        item_id=2,
        segment_id=3,
        title="source",
        excerpt="evidence",
        url="https://example.test",
    )

    async def slow_composer(_messages, _info):
        # Leave retrieval enough headroom on slower CI/Windows hosts while
        # keeping the answer phase deterministically beyond its own budget.
        await asyncio.sleep(1.0)
        return ModelResponse(parts=[TextPart("unreachable draft")])

    result = await KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="retrieval stop"),
        replace(Settings(), agent_timeout_seconds=0.5),
        lambda _: FakeServices([citation]),
        composer_model=FunctionModel(slow_composer),
    ).run(request())

    assert result.answer.status == "ok"
    assert result.answer.error_code is None
    assert result.answer.text.startswith("自动总结未完成")
    assert "unreachable draft" not in result.answer.text
    assert len(result.new_messages) == 2


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
async def test_composer_top_five_retry_does_not_retrieve_again():
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

    composer_calls = []

    def composer(_messages, info):
        composer_calls.append(info)
        assert info.output_tools == []
        ids = list(range(1, 7)) if len(composer_calls) == 1 else list(range(1, 6))
        return ModelResponse(parts=[TextPart(json.dumps({
            "sections": [{"text": "grouped sources", "citation_ids": ids}]
        }))])

    result = await KnowledgeAgent(
        TestModel(call_tools=["search_segments"], custom_output_text="retrieval stop"),
        replace(Settings(), agent_timeout_seconds=2),
        lambda _: services,
        composer_model=FunctionModel(composer),
    ).run(request())

    assert result.answer.status == "ok"
    assert services.calls == ["search_segments"]
    assert len(composer_calls) == 2
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
        composer_model=composer_for(3),
    )
    exhausted = await limited.run(request())
    assert exhausted.answer.status == "ok"
    assert exhausted.answer.error_code is None
