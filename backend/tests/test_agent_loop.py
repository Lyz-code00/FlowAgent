import httpx

from app.agent.loop import AgentLoop
from app.llm.provider import (
    LLMOutput,
    LLMProvider,
    OpenAICompatibleProvider,
    ToolCall,
)
from app.schemas.message import UnifiedMessage
from app.services.conversation_service import HistoryMessage
from app.tools.runner import ToolRunner
from app.tools.context import ToolContext


class FakeTraceService:
    def __init__(self) -> None:
        self.steps: list[dict] = []

    async def record_step(self, **kwargs) -> None:
        self.steps.append(kwargs)


class EndlessToolProvider(LLMProvider):
    model_name = "endless-tool-model"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, *, messages, tools) -> LLMOutput:
        self.calls += 1
        return LLMOutput(
            tool_calls=[
                ToolCall(id=f"call-{self.calls}", name="missing_tool", arguments={})
            ]
        )


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

    assert provider.calls == 3
    assert response.metadata == {"steps": 3, "stopped": "max_steps"}
    assert len(traces.steps) == 6


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
