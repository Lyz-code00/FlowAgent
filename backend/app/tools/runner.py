import asyncio
from time import monotonic

from pydantic import ValidationError

from app.llm.provider import ToolCall
from app.services.permission_service import PermissionDeniedError, PermissionService
from app.services.trace_service import TraceService
from app.tools.base import Tool, ToolResponse
from app.tools.context import ToolContext


class ToolRunner:
    def __init__(
        self,
        *,
        trace_service: TraceService,
        permission_service: PermissionService | None = None,
        tools: list[Tool] | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        self.trace_service = trace_service
        self.permission_service = permission_service or PermissionService()
        self.timeout_seconds = timeout_seconds
        self._tools = {tool.name: tool for tool in tools or []}

    def definitions(self) -> list[dict]:
        return [tool.definition() for tool in self._tools.values()]

    async def run(
        self,
        *,
        call: ToolCall,
        run_id: int,
        step_no: int,
        context: ToolContext,
    ) -> ToolResponse:
        started = monotonic()
        tool = self._tools.get(call.name)
        try:
            if tool is None:
                raise LookupError(f"unknown tool '{call.name}'")
            args = tool.args_model.model_validate(call.arguments)
            self.permission_service.require(
                role=context.user_role, permission=tool.permission
            )
            async with asyncio.timeout(self.timeout_seconds):
                result = await tool.run(context, args)
        except ValidationError as exc:
            result = self._error_response(
                call.name, "invalid tool arguments", exc.errors(include_url=False)
            )
        except PermissionDeniedError as exc:
            result = self._error_response(call.name, "permission denied", str(exc))
        except TimeoutError:
            result = self._error_response(call.name, "tool timeout", "execution timed out")
        except Exception as exc:
            result = self._error_response(call.name, "tool execution failed", str(exc))

        result.latency_ms = int((monotonic() - started) * 1000)
        await self.trace_service.record_step(
            run_id=run_id,
            step_no=step_no,
            kind="tool",
            status="succeeded" if result.success else "failed",
            name=call.name,
            input_data=call.arguments,
            output_data=result.display_data,
            latency_ms=result.latency_ms,
            error=result.error,
        )
        return result

    @staticmethod
    def _error_response(name: str, summary: str, detail) -> ToolResponse:
        return ToolResponse(
            tool_name=name,
            success=False,
            llm_content=f"{summary}: {detail}",
            error=summary,
        )
