import json
from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

from app.services.incident_service import IncidentService
from app.tools.base import StrictToolArgs, Tool, ToolResponse
from app.tools.context import ToolContext


IncidentStatus = Literal["open", "investigating", "mitigated", "resolved"]
IncidentSeverity = Literal["P0", "P1", "P2", "P3", "P4", "unknown"]


class IncidentSearchArgs(StrictToolArgs):
    query: str | None = Field(default=None, max_length=1000)
    status: IncidentStatus | None = None
    severity: IncidentSeverity | None = None
    service: str | None = Field(default=None, max_length=255)
    limit: int = Field(default=10, ge=1, le=50)


class IncidentSaveArgs(StrictToolArgs):
    title: str = Field(min_length=1, max_length=512)
    summary: str = Field(min_length=1, max_length=10_000)
    status: IncidentStatus = "open"
    severity: IncidentSeverity = "unknown"
    service: str | None = Field(default=None, max_length=255)
    error_code: str | None = Field(default=None, max_length=128)
    occurred_at: str | None = Field(default=None, max_length=64)
    root_cause: str | None = Field(default=None, max_length=10_000)
    evidence: list[str] = Field(default_factory=list, max_length=50)
    source_url: HttpUrl | None = None


class IncidentSearchTool(Tool):
    name = "incident_search"
    description = (
        "Search tenant-isolated historical incidents by symptom, service, error code, "
        "status, or severity. Use this during failure diagnosis before proposing a root cause."
    )
    args_model = IncidentSearchArgs
    retryable = True

    def __init__(self, service: IncidentService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = IncidentSearchArgs.model_validate(args)
        incidents = await self.service.search(
            tenant_id=context.tenant_id,
            **values.model_dump(),
        )
        data = [asdict(item) for item in incidents]
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=(
                json.dumps(data, ensure_ascii=False)
                + "\n这些是历史记录而非当前运行状态；结论必须区分事实和推断。"
            ),
            display_data={"incidents": data},
        )


class IncidentSaveTool(Tool):
    name = "incident_save"
    description = (
        "Persist a structured incident for future diagnosis. Only call when the user "
        "explicitly asks to record, save, or archive an incident."
    )
    permission = "incident_write"
    args_model = IncidentSaveArgs

    def __init__(self, service: IncidentService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = IncidentSaveArgs.model_validate(args)
        payload = values.model_dump(mode="json")
        incident = await self.service.create(
            tenant_id=context.tenant_id,
            created_by_user_id=context.user_id,
            **payload,
        )
        data = asdict(incident)
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data=data,
        )
