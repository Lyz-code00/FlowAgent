import httpx
from pydantic import BaseModel

from app.agent.loop import AgentLoop
from app.llm.provider import (
    LLMOutput,
    LLMProvider,
    OpenAICompatibleProvider,
    ToolCall,
)
from app.schemas.message import Attachment, UnifiedMessage
from app.services.document_service import DocumentService
from app.services.conversation_service import HistoryMessage
from app.tools.runner import ToolRunner
from app.tools.context import ToolContext
from app.tools.base import Tool, ToolResponse
from app.tools.document import GenerateDocumentTool


class FakeTraceService:
    def __init__(self) -> None:
        self.steps: list[dict] = []

    async def record_step(self, **kwargs) -> None:
        self.steps.append(kwargs)


class EndlessToolProvider(LLMProvider):
    model_name = "endless-tool-model"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self, *, messages, tools, tool_choice=None, disable_thinking=False
    ) -> LLMOutput:
        self.calls += 1
        return LLMOutput(
            tool_calls=[
                ToolCall(id=f"call-{self.calls}", name="missing_tool", arguments={})
            ]
        )


class FinalAnswerProvider(LLMProvider):
    model_name = "final-answer-model"

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    async def complete(
        self, *, messages, tools, tool_choice=None, disable_thinking=False
    ) -> LLMOutput:
        self.calls += 1
        return LLMOutput(
            tool_calls=[
                ToolCall(
                    id="final",
                    name="submit_final_answer",
                    arguments={"answer": self.answer, "status": "resolved"},
                )
            ]
        )


class DocumentProvider(LLMProvider):
    model_name = "document-model"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self, *, messages, tools, tool_choice=None, disable_thinking=False
    ) -> LLMOutput:
        self.calls += 1
        if self.calls == 1:
            return LLMOutput(
                tool_calls=[
                    ToolCall(
                        id="document",
                        name="generate_document",
                        arguments={
                            "title": "测试报告",
                            "sections": [
                                {"heading": "结论", "paragraphs": ["已完成"]}
                            ],
                        },
                    )
                ]
            )
        return LLMOutput(
            tool_calls=[
                ToolCall(
                    id="final",
                    name="submit_final_answer",
                    arguments={"answer": "Word 文档已生成并附上。", "status": "resolved"},
                )
            ]
        )


class CitationRepairProvider(LLMProvider):
    model_name = "citation-repair-model"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self, *, messages, tools, tool_choice=None, disable_thinking=False
    ) -> LLMOutput:
        self.calls += 1
        if self.calls == 1:
            return LLMOutput(
                tool_calls=[ToolCall(id="knowledge", name="knowledge_search", arguments={})]
            )
        if self.calls == 2:
            return LLMOutput(
                tool_calls=[
                    ToolCall(
                        id="bad-final",
                        name="submit_final_answer",
                        arguments={"answer": "依据知识库，令牌需要刷新。", "status": "resolved"},
                    )
                ]
            )
        return LLMOutput(
            tool_calls=[
                ToolCall(
                    id="good-final",
                    name="submit_final_answer",
                    arguments={"answer": "依据知识库，令牌需要刷新。[1]", "status": "resolved", "citations": [1]},
                )
            ]
        )


class CitationKnowledgeTool(Tool):
    name = "knowledge_search"
    description = "Return one cited knowledge result."

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content='[{"citation_id": 1, "content": "刷新令牌"}]',
            display_data={"results": [{"citation_id": 1, "content": "刷新令牌"}]},
        )


class FlakyReadTool(Tool):
    name = "flaky_read"
    description = "Read transient data."
    retryable = True

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        self.calls += 1
        if self.calls < 3:
            raise RuntimeError("temporary failure")
        return ToolResponse(tool_name=self.name, success=True, llm_content="ok")


class BoundedReadTool(Tool):
    name = "bounded_read"
    description = "Fail quickly with a tool-specific retry budget."
    retryable = True
    max_attempts = 1
    timeout_seconds = 0.01

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        self.calls += 1
        raise RuntimeError("provider unavailable")


async def test_read_tool_retries_with_bounded_attempts() -> None:
    traces = FakeTraceService()
    tool = FlakyReadTool()
    runner = ToolRunner(
        trace_service=traces,  # type: ignore[arg-type]
        tools=[tool],
        max_attempts=3,
        retry_backoff_seconds=0,
    )
    response = await runner.run(
        call=ToolCall(id="retry", name=tool.name, arguments={}),
        run_id=1,
        step_no=1,
        context=ToolContext(
            tenant_id=1,
            user_id=1,
            user_role="lead",
            conversation_id=1,
            source_message_id=1,
            external_message_id="message",
        ),
    )
    assert response.success is True
    assert response.display_data["retry_attempts"] == 3
    assert tool.calls == 3
    assert len(traces.steps) == 1


async def test_tool_can_override_global_retry_budget() -> None:
    traces = FakeTraceService()
    tool = BoundedReadTool()
    response = await ToolRunner(
        trace_service=traces,  # type: ignore[arg-type]
        tools=[tool],
        max_attempts=3,
        retry_backoff_seconds=0,
    ).run(
        call=ToolCall(id="bounded", name=tool.name, arguments={}),
        run_id=1,
        step_no=1,
        context=ToolContext(
            tenant_id=1,
            user_id=1,
            user_role="lead",
            conversation_id=1,
            source_message_id=1,
            external_message_id="message",
        ),
    )
    assert response.success is False
    assert tool.calls == 1


async def test_agent_rejects_missing_citation_and_asks_model_to_repair() -> None:
    traces = FakeTraceService()
    provider = CitationRepairProvider()
    agent = AgentLoop(
        provider=provider,
        tool_runner=ToolRunner(
            trace_service=traces,  # type: ignore[arg-type]
            tools=[CitationKnowledgeTool()],
        ),
        trace_service=traces,  # type: ignore[arg-type]
        max_steps=4,
    )
    response = await agent.run(
        UnifiedMessage(
            platform="feishu",
            tenant_id="tenant",
            external_user_id="user",
            conversation_id="conversation",
            message_id="citation-message",
            message_type="text",
            text="令牌过期怎么办",
        ),
        history=[HistoryMessage(role="user", content="令牌过期怎么办")],
        run_id=1,
        tool_context=ToolContext(
            tenant_id=1,
            user_id=1,
            user_role="lead",
            conversation_id=1,
            source_message_id=1,
            external_message_id="citation-message",
        ),
    )
    assert provider.calls == 3
    assert response.metadata["citations"] == [1]
    assert "[1]" in response.content


async def test_agent_loop_stops_at_configured_max_steps() -> None:
    traces = FakeTraceService()
    provider = EndlessToolProvider()
    runner = ToolRunner(trace_service=traces)  # type: ignore[arg-type]
    agent = AgentLoop(
        provider=provider,
        tool_runner=runner,
        trace_service=traces,  # type: ignore[arg-type]
        max_steps=3,
    )
    message = UnifiedMessage(
        platform="feishu",
        tenant_id="tenant",
        external_user_id="user",
        conversation_id="conversation",
        message_id="message",
        message_type="text",
        text="do work",
    )

    response = await agent.run(
        message,
        history=[HistoryMessage(role="user", content="do work")],
        run_id=1,
        tool_context=ToolContext(
            tenant_id=1,
            user_id=1,
            user_role="lead",
            conversation_id=1,
            source_message_id=1,
            external_message_id="message",
        ),
    )

    assert provider.calls == 4
    assert response.metadata == {
        "steps": 4,
        "stopped": True,
        "structured": False,
        "status": "partial",
    }
    assert "尚未完成" in response.content
    assert len(traces.steps) == 7


async def test_greeting_is_understood_by_model_instead_of_keyword_bypass() -> None:
    traces = FakeTraceService()
    provider = FinalAnswerProvider("你好，我记得我们刚才在处理 Issue #3。")
    agent = AgentLoop(
        provider=provider,
        tool_runner=ToolRunner(trace_service=traces),  # type: ignore[arg-type]
        trace_service=traces,  # type: ignore[arg-type]
    )
    message = UnifiedMessage(
        platform="feishu",
        tenant_id="tenant",
        external_user_id="user",
        conversation_id="conversation",
        message_id="hello",
        message_type="text",
        text="你好",
    )
    response = await agent.run(
        message,
        history=[HistoryMessage(role="user", content="你好")],
        run_id=1,
        tool_context=ToolContext(
            tenant_id=1,
            user_id=1,
            user_role="member",
            conversation_id=1,
            source_message_id=1,
            external_message_id="hello",
        ),
    )
    assert provider.calls == 1
    assert "Issue #3" in response.content
    assert response.metadata["status"] == "resolved"


async def test_agent_loop_preserves_generated_document_for_channel_delivery() -> None:
    traces = FakeTraceService()
    provider = DocumentProvider()
    agent = AgentLoop(
        provider=provider,
        tool_runner=ToolRunner(
            trace_service=traces,  # type: ignore[arg-type]
            tools=[GenerateDocumentTool(DocumentService())],
        ),
        trace_service=traces,  # type: ignore[arg-type]
    )
    message = UnifiedMessage(
        platform="feishu",
        tenant_id="tenant",
        external_user_id="user",
        conversation_id="conversation",
        message_id="document",
        message_type="text",
        text="生成 Word 文档",
    )
    response = await agent.run(
        message,
        history=[HistoryMessage(role="user", content="生成 Word 文档")],
        run_id=1,
        tool_context=ToolContext(
            tenant_id=1,
            user_id=1,
            user_role="member",
            conversation_id=1,
            source_message_id=1,
            external_message_id="document",
        ),
    )
    assert provider.calls == 2
    assert response.content == "Word 文档已生成并附上。"
    assert response.files[0].name == "测试报告.docx"
    assert response.files[0].data.startswith(b"PK")


def test_verified_github_url_is_not_filtered_or_duplicated() -> None:
    traces = FakeTraceService()
    provider = FinalAnswerProvider("链接：https://github.com/org/repo/issues/7")
    agent = AgentLoop(
        provider=provider,
        tool_runner=ToolRunner(trace_service=traces),  # type: ignore[arg-type]
        trace_service=traces,  # type: ignore[arg-type]
    )
    response = agent._build_response(
        ToolCall(
            id="final",
            name="submit_final_answer",
            arguments={
                "answer": "链接：https://github.com/org/repo/issues/7",
                "status": "resolved",
            },
        ),
        2,
        {"number": 7, "html_url": "https://github.com/org/repo/issues/7"},
        ["https://github.com/org/repo/issues/7"],
    )
    assert response.content.count("https://github.com/org/repo/issues/7") == 1


def test_partial_response_always_exposes_unresolved_items_and_next_step() -> None:
    traces = FakeTraceService()
    agent = AgentLoop(
        provider=FinalAnswerProvider("已完成图片支持。"),
        tool_runner=ToolRunner(trace_service=traces),  # type: ignore[arg-type]
        trace_service=traces,  # type: ignore[arg-type]
    )
    response = agent._build_response(
        ToolCall(
            id="final",
            name="submit_final_answer",
            arguments={
                "answer": "已完成图片支持。",
                "status": "partial",
                "unresolved_items": ["语音转写服务尚未配置"],
                "next_step": "配置一个兼容的语音转写接口。",
            },
        ),
        2,
    )
    assert "未完成事项" in response.content
    assert "语音转写服务尚未配置" in response.content
    assert "下一步" in response.content


def test_attachment_content_contains_images_and_extracted_files() -> None:
    message = UnifiedMessage(
        platform="feishu",
        tenant_id="tenant",
        external_user_id="user",
        conversation_id="conversation",
        message_id="multimodal",
        message_type="image",
        text="分析图片和文件",
        attachments=[
            Attachment(
                type="image",
                mime_type="image/png",
                data_base64="aW1hZ2U=",
            ),
            Attachment(type="file", name="notes.txt", extracted_text="重要待办"),
        ],
    )
    content = AgentLoop._content_from_message(message)
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert "已成功下载并附加真实图片" in content[0]["text"]
    assert "不得声称未收到图片" in content[0]["text"]
    assert "重要待办" in content[0]["text"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_openai_compatible_provider_parses_tool_calls() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://llm.example/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "function": {
                                        "name": "knowledge_search",
                                        "arguments": '{"query":"login 401"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"total_tokens": 42},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://llm.example/v1",
            api_key="test-key",
            model="test-model",
            client=client,
        )
        output = await provider.complete(
            messages=[{"role": "user", "content": "help"}],
            tools=[
                {
                    "name": "knowledge_search",
                    "description": "Search knowledge",
                    "parameters": {"type": "object"},
                }
            ],
        )

    assert output.tool_calls[0].name == "knowledge_search"
    assert output.tool_calls[0].arguments == {"query": "login 401"}
    assert output.usage == {"total_tokens": 42}


async def test_openai_provider_selects_vision_model_for_image_content() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        assert payload["model"] == "vision-model"
        assert payload["messages"][0]["content"][1]["type"] == "image_url"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "图片里是控制台截图"}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://llm.example/v1",
            api_key="test-key",
            model="text-model",
            vision_model="vision-model",
            client=client,
        )
        output = await provider.complete(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "这是什么？"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,aW1hZ2U="},
                        },
                    ],
                }
            ],
            tools=[],
        )
    assert output.content == "图片里是控制台截图"
