from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Any

from app.agent.loop import Agent
from app.channels.base import ChannelAdapter
from app.schemas.message import AgentResponse
from app.services.conversation_service import ConversationService
from app.services.trace_service import TraceService
from app.tools.context import ToolContext


@dataclass(frozen=True)
class ProcessResult:
    status: str
    message_id: str | None = None


class MessageGateway:
    def __init__(
        self,
        *,
        adapter: ChannelAdapter,
        agent: Agent | None = None,
        agent_resolver: Callable[[], Awaitable[Agent]] | None = None,
        conversation_service: ConversationService,
        trace_service: TraceService,
        context_turns: int = 10,
    ) -> None:
        self.adapter = adapter
        if agent is None and agent_resolver is None:
            raise ValueError("agent or agent_resolver is required")
        self.agent = agent
        self.agent_resolver = agent_resolver
        self.conversation_service = conversation_service
        self.trace_service = trace_service
        self.context_turns = context_turns

    async def process(self, payload: dict[str, Any]) -> ProcessResult:
        if not self.adapter.should_handle(payload):
            return ProcessResult(status="ignored")
        message = self.adapter.parse_event(payload)
        if not message.message_id:
            return ProcessResult(status="ignored")
        inbound = await self.conversation_service.accept_inbound(message)
        if inbound is None:
            return ProcessResult(status="duplicate", message_id=message.message_id)

        history = await self.conversation_service.recent_history(
            inbound.conversation_id, turns=self.context_turns
        )
        agent = (
            await self.agent_resolver()
            if self.agent_resolver is not None
            else self.agent
        )
        assert agent is not None
        run_id = await self.trace_service.start(
            conversation_id=inbound.conversation_id,
            source_message_id=inbound.message_id,
            model=agent.model_name,
        )
        run_error: str | None = None
        try:
            response = await agent.run(
                message,
                history=history,
                run_id=run_id,
                tool_context=ToolContext(
                    tenant_id=inbound.tenant_id,
                    user_id=inbound.user_id,
                    user_role=inbound.role,
                    conversation_id=inbound.conversation_id,
                    source_message_id=inbound.message_id,
                    external_message_id=message.message_id,
                ),
            )
        except Exception as exc:
            run_error = str(exc)
            response = AgentResponse(
                content="当前 AI 服务不可用，本次消息已保存，请稍后重试。",
                metadata={"error": "llm_unavailable"},
            )

        await self.conversation_service.save_assistant(
            inbound.conversation_id, response.content
        )
        await self.trace_service.finish(
            run_id,
            final_answer=response.content,
            error=run_error,
        )
        await self.adapter.send_message(
            source_message_id=message.message_id,
            content=response.content,
        )
        return ProcessResult(status="processed", message_id=message.message_id)
