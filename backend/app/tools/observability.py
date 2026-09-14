import json
from dataclasses import asdict

from pydantic import BaseModel, Field

from app.services.observability_service import ObservabilityService
from app.tools.base import StrictToolArgs, Tool, ToolResponse
from app.tools.context import ToolContext


class MonitorHealthArgs(StrictToolArgs):
    service: str | None = Field(default=None, max_length=255)


class MonitorMetricArgs(StrictToolArgs):
    query: str = Field(min_length=1, max_length=2000)
    time: str | None = Field(default=None, max_length=64)


class MonitorLogArgs(StrictToolArgs):
    query: str = Field(min_length=1, max_length=2000)
    minutes: int = Field(default=30, ge=1, le=1440)
    limit: int = Field(default=100, ge=1, le=500)


class MonitorErrorArgs(StrictToolArgs):
    query: str = Field(default="is:unresolved", max_length=1000)
    limit: int = Field(default=20, ge=1, le=100)


class MonitorHealthTool(Tool):
    name = "monitor_service_health"
    description = "Query current health endpoints that administrators configured for services."
    args_model = MonitorHealthArgs
    retryable = True

    def __init__(self, service: ObservabilityService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = MonitorHealthArgs.model_validate(args)
        data = [asdict(item) for item in await self.service.health(service=values.service)]
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data={"services": data},
        )


class MonitorMetricTool(Tool):
    name = "monitor_metric_query"
    description = (
        "Run a read-only Prometheus instant query for current metrics, error rates, "
        "latency, or MQ consumer lag."
    )
    args_model = MonitorMetricArgs
    retryable = True

    def __init__(self, service: ObservabilityService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = MonitorMetricArgs.model_validate(args)
        data = await self.service.prometheus_query(**values.model_dump())
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data=data,
        )


class MonitorLogTool(Tool):
    name = "monitor_log_search"
    description = "Search recent Loki logs using a read-only LogQL query."
    args_model = MonitorLogArgs
    retryable = True

    def __init__(self, service: ObservabilityService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = MonitorLogArgs.model_validate(args)
        data = await self.service.loki_search(**values.model_dump())
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data=data,
        )


class MonitorErrorTool(Tool):
    name = "monitor_error_search"
    description = "Search current Sentry project issues using Sentry search syntax."
    args_model = MonitorErrorArgs
    retryable = True

    def __init__(self, service: ObservabilityService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = MonitorErrorArgs.model_validate(args)
        data = await self.service.sentry_search(**values.model_dump())
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data=data,
        )
