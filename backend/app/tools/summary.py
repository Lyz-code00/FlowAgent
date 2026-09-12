import json

from pydantic import BaseModel, Field

from app.services.summary_service import SummaryService
from app.tools.base import StrictToolArgs, Tool, ToolResponse
from app.tools.context import ToolContext


class ActionItem(StrictToolArgs):
    content: str = Field(min_length=1, max_length=1000)
    owner: str | None = Field(default=None, max_length=255)
    due_date: str | None = Field(default=None, max_length=100)
    priority: str | None = Field(default=None, max_length=32)
    status: str = Field(default="pending", max_length=32)


class SaveSummaryArgs(StrictToolArgs):
    summary: str = Field(min_length=1, max_length=10_000)
    decisions: list[str] = Field(default_factory=list, max_length=50)
    bugs: list[str] = Field(default_factory=list, max_length=50)
    action_items: list[ActionItem] = Field(default_factory=list, max_length=100)


class SaveConversationSummaryTool(Tool):
    name = "save_conversation_summary"
    description = (
        "Persist a structured conversation summary. You MUST call this when the user "
        "explicitly asks to summarize the discussion or extract decisions, bugs, or todos. "
        "Never infer missing owners or deadlines; use null when absent."
    )
    args_model = SaveSummaryArgs

    def __init__(self, service: SummaryService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = SaveSummaryArgs.model_validate(args)
        data = await self.service.save(
            context=context,
            summary=values.summary,
            decisions=values.decisions,
            bugs=values.bugs,
            action_items=[item.model_dump() for item in values.action_items],
        )
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data=data,
        )
