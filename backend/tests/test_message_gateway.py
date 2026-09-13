import asyncio
from typing import Any

from sqlalchemy import func, select

from app.agent.loop import Agent
from app.channels.base import ChannelAdapter
from app.db.models import (
    AgentRun,
    AgentStep,
    ChannelAccount,
    Conversation,
    ConversationSummary,
    Message,
)
from app.db.session import create_engine, create_session_factory, create_tables
from app.schemas.message import AgentResponse, UnifiedMessage
from app.services.conversation_service import ConversationService, HistoryMessage
from app.services.identity_service import IdentityService
from app.services.message_gateway import MessageGateway
from app.services.trace_service import TraceService
from app.tools.context import ToolContext


class FakeAdapter(ChannelAdapter):
    def __init__(self) -> None:
        self.replies: list[tuple[str, str]] = []

    def verify_event(self, *, body: bytes, headers, payload) -> None:
        return None

    def should_handle(self, payload: dict[str, Any]) -> bool:
        return True

    def parse_event(self, payload: dict[str, Any]) -> UnifiedMessage:
        return UnifiedMessage(
            platform="feishu",
            tenant_id="tenant",
            external_user_id="user",
            conversation_id="conversation",
            message_id=payload["message_id"],
            message_type="text",
            text=payload.get("text", "hello"),
        )

    async def send_message(self, *, source_message_id: str, content: str) -> None:
        self.replies.append((source_message_id, content))


class FakeAgent(Agent):
    model_name = "fake-model"

    def __init__(self, trace_service: TraceService) -> None:
        self.trace_service = trace_service
        self.histories: list[list[HistoryMessage]] = []

    async def run(
        self,
        message: UnifiedMessage,
        *,
        history: list[HistoryMessage],
        run_id: int,
        tool_context: ToolContext,
    ) -> AgentResponse:
        self.histories.append(history)
        await self.trace_service.record_step(
            run_id=run_id,
            step_no=1,
            kind="llm",
            status="succeeded",
            name=self.model_name,
        )
        await asyncio.sleep(0)
        return AgentResponse(content=f"reply: {message.text}")


async def build_gateway(database_url: str):
    engine = create_engine(database_url)
    await create_tables(engine)
    factory = create_session_factory(engine)
    conversations = ConversationService(factory, IdentityService())
    traces = TraceService(factory)
    adapter = FakeAdapter()
    agent = FakeAgent(traces)
    gateway = MessageGateway(
        adapter=adapter,
        agent=agent,
        conversation_service=conversations,
        trace_service=traces,
        context_turns=10,
    )
    return engine, factory, adapter, agent, gateway


async def test_duplicate_message_is_processed_only_once(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'gateway.db'}"
    engine, factory, adapter, agent, gateway = await build_gateway(database_url)
    try:
        first, second = await asyncio.gather(
            gateway.process({"message_id": "om-1"}),
            gateway.process({"message_id": "om-1"}),
        )

        assert {first.status, second.status} == {"processed", "duplicate"}
        assert adapter.replies == [("om-1", "reply: hello")]
        async with factory() as session:
            assert await session.scalar(select(func.count(Message.id))) == 2
            assert await session.scalar(select(func.count(ChannelAccount.id))) == 1
            assert await session.scalar(select(func.count(AgentRun.id))) == 1
            assert await session.scalar(select(func.count(AgentStep.id))) == 1
    finally:
        await engine.dispose()


async def test_context_is_limited_to_ten_turns(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'history.db'}"
    engine, factory, adapter, agent, gateway = await build_gateway(database_url)
    try:
        for index in range(12):
            result = await gateway.process(
                {"message_id": f"om-{index}", "text": f"message {index}"}
            )
            assert result.status == "processed"

        final_history = agent.histories[-1]
        assert len(final_history) == 20
        assert final_history[-1].content == "message 11"
        assert final_history[0].content == "reply: message 1"
    finally:
        await engine.dispose()


async def test_context_includes_saved_summary_and_old_issue_links(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}"
    engine, factory, adapter, agent, gateway = await build_gateway(database_url)
    try:
        for index in range(12):
            text = (
                "Issue #3 地址 https://github.com/org/repo/issues/3"
                if index == 0
                else f"message {index}"
            )
            assert (
                await gateway.process({"message_id": f"om-{index}", "text": text})
            ).status == "processed"
        async with factory() as session:
            conversation = await session.scalar(select(Conversation))
            source = await session.scalar(
                select(Message).where(Message.external_message_id == "om-0")
            )
            assert conversation is not None and source is not None and source.user_id
            session.add(
                ConversationSummary(
                    tenant_id=conversation.tenant_id,
                    conversation_id=conversation.id,
                    source_message_id=source.id,
                    created_by_user_id=source.user_id,
                    summary="用户正在验收飞书到 GitHub 的闭环。",
                    decisions=["真实写操作必须调用工具"],
                    bugs=["链接曾被过滤"],
                    action_items=[
                        {
                            "content": "验证 Issue #3",
                            "status": "pending",
                            "owner": None,
                            "due_date": None,
                        }
                    ],
                    status="confirmed",
                )
            )
            await session.commit()

        assert (
            await gateway.process({"message_id": "om-12", "text": "继续"})
        ).status == "processed"
        final_history = agent.histories[-1]
        assert final_history[0].role == "system"
        assert "长期记忆" in final_history[0].content
        assert "飞书到 GitHub" in final_history[0].content
        assert "https://github.com/org/repo/issues/3" in final_history[0].content
        assert final_history[-1].content == "继续"
    finally:
        await engine.dispose()
