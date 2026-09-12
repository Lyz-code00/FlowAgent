import json
from typing import Literal

from pydantic import BaseModel, Field

from app.services.github_service import GitHubService
from app.services.tool_operation_service import ToolOperationService
from app.tools.base import StrictToolArgs, Tool, ToolResponse
from app.tools.context import ToolContext


class SearchIssueArgs(StrictToolArgs):
    query: str = Field(min_length=1, max_length=256)
    state: Literal["open", "closed", "all"] = "all"
    labels: list[str] = Field(default_factory=list, max_length=10)


class GetIssueArgs(StrictToolArgs):
    issue_number: int = Field(ge=1)


class CreateIssueArgs(StrictToolArgs):
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1, max_length=65536)
    labels: list[str] | None = Field(default=None, max_length=10)
    assignee: str | None = Field(default=None, max_length=100)


class GitHubSearchIssueTool(Tool):
    name = "github_search_issue"
    description = "Search issues in the configured GitHub repository."
    args_model = SearchIssueArgs

    def __init__(self, service: GitHubService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = SearchIssueArgs.model_validate(args)
        issues = await self.service.search_issues(
            query=values.query, state=values.state, labels=values.labels
        )
        data = [issue.model_dump() for issue in issues]
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data={"issues": data},
        )


class GitHubGetIssueTool(Tool):
    name = "github_get_issue"
    description = "Read one issue from the configured GitHub repository."
    args_model = GetIssueArgs

    def __init__(self, service: GitHubService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = GetIssueArgs.model_validate(args)
        issue = await self.service.get_issue(values.issue_number)
        data = issue.model_dump()
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data=data,
        )


class GitHubCreateIssueTool(Tool):
    name = "github_create_issue"
    description = "Create a real issue in the configured GitHub repository."
    permission = "github_issue_write"
    args_model = CreateIssueArgs

    def __init__(
        self,
        service: GitHubService,
        operations: ToolOperationService,
        *,
        default_labels: list[str] | None = None,
        default_assignee: str = "",
    ) -> None:
        self.service = service
        self.operations = operations
        self.default_labels = default_labels or []
        self.default_assignee = default_assignee

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = CreateIssueArgs.model_validate(args)
        claim = await self.operations.claim(context=context, tool_name=self.name)
        if not claim.should_execute:
            if claim.status == "succeeded" and claim.result_data:
                return ToolResponse(
                    tool_name=self.name,
                    success=True,
                    llm_content=json.dumps(claim.result_data, ensure_ascii=False),
                    display_data={**claim.result_data, "idempotent_replay": True},
                )
            return ToolResponse(
                tool_name=self.name,
                success=False,
                llm_content="The same create operation is already in progress.",
                error="operation already in progress",
            )

        try:
            issue = await self.service.create_issue(
                title=values.title,
                body=values.body,
                labels=values.labels
                if values.labels is not None
                else self.default_labels,
                assignee=values.assignee or self.default_assignee or None,
            )
            data = issue.model_dump()
            await self.operations.succeed(
                context=context,
                tool_name=self.name,
                external_id=str(issue.number),
                result_data=data,
            )
        except Exception as exc:
            await self.operations.fail(
                context=context, tool_name=self.name, error=str(exc)
            )
            raise
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data=data,
        )
