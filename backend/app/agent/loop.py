from time import monotonic
from typing import Protocol

from app.llm.provider import ChatMessage, LLMProvider
from app.schemas.message import AgentResponse, UnifiedMessage
from app.services.conversation_service import HistoryMessage
from app.services.trace_service import TraceService
from app.tools.runner import ToolRunner
from app.tools.context import ToolContext


SYSTEM_PROMPT = """你是 FlowAgent，一名面向软件研发团队的协同助手。
你必须基于当前会话信息作答；信息不足时明确说明，不得伪造 Issue、链接、负责人或内部资料。
使用 knowledge_search 的证据作答时，必须保留工具给出的 [数字] Citation 标记。
涉及真实写操作时必须调用工具，不能只在文本中声称已经完成。
当前没有可用工具时，请直接说明能力边界，并给出下一步建议。"""


class Agent(Protocol):
    model_name: str

    async def run(
        self,
        message: UnifiedMessage,
        *,
        history: list[HistoryMessage],
        run_id: int,
        tool_context: ToolContext,
    ) -> AgentResponse: ...


class AgentLoop:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        tool_runner: ToolRunner,
        trace_service: TraceService,
        max_steps: int = 5,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.provider = provider
        self.tool_runner = tool_runner
        self.trace_service = trace_service
        self.max_steps = max_steps
        self.system_prompt = system_prompt
        self.model_name = provider.model_name

    async def run(
        self,
        message: UnifiedMessage,
        *,
        history: list[HistoryMessage],
        run_id: int,
        tool_context: ToolContext,
    ) -> AgentResponse:
        messages: list[ChatMessage] = [
            {"role": "system", "content": self.system_prompt}
        ]
        messages.extend(
            {"role": item.role, "content": item.content} for item in history
        )

        for step_no in range(1, self.max_steps + 1):
            started = monotonic()
            try:
                output = await self.provider.complete(
                    messages=messages,
                    tools=self.tool_runner.definitions(),
                )
            except Exception as exc:
                await self.trace_service.record_step(
                    run_id=run_id,
                    step_no=step_no,
                    kind="llm",
                    status="failed",
                    name=self.provider.model_name,
                    latency_ms=int((monotonic() - started) * 1000),
                    error=str(exc),
                )
                raise

            await self.trace_service.record_step(
                run_id=run_id,
                step_no=step_no,
                kind="llm",
                status="succeeded",
                name=self.provider.model_name,
                output_data={
                    "content": output.content,
                    "tool_calls": [call.model_dump() for call in output.tool_calls],
                    "usage": output.usage,
                },
                latency_ms=int((monotonic() - started) * 1000),
            )
            if not output.tool_calls:
                return AgentResponse(
                    content=output.content or "当前没有生成可用回答，请稍后重试。",
                    metadata={"steps": step_no, "model": self.provider.model_name},
                )

            messages.append(output.as_assistant_message())
            for call in output.tool_calls:
                tool_result = await self.tool_runner.run(
                    call=call,
                    run_id=run_id,
                    step_no=step_no,
                    context=tool_context,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": tool_result.llm_content,
                    }
                )

        return AgentResponse(
            content=(
                "本次请求已达到最大处理步数。我已停止继续调用工具，以避免循环执行；"
                "请缩小问题范围后重试。"
            ),
            metadata={"steps": self.max_steps, "stopped": "max_steps"},
        )
