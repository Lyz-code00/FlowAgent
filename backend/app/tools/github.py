import json
from typing import Literal

from pydantic import BaseModel, Field

from app.services.github_service import GitHubService
from app.services.confirmation_service import ConfirmationService
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
    confirmation_code: str | None = Field(default=None, min_length=8, max_length=16)


class RecentChangesArgs(StrictToolArgs):
    limit: int = Field(default=10, ge=1, le=20)


class GitHubSearchIssueTool(Tool):
    name = "github_search_issue"
    description = "Search issues in the configured GitHub repository."
    args_model = SearchIssueArgs
    retryable = True

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
    retryable = True

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
    description = (
        "Create a real issue in the configured GitHub repository. P0/P1 issues require "
        "a second user confirmation: first call without confirmation_code, tell the user "
        "the returned code, then call again with the same arguments and that code only "
        "after the user explicitly confirms."
    )
    permission = "github_issue_write"
    args_model = CreateIssueArgs

    def __init__(
        self,
        service: GitHubService,
        operations: ToolOperationService,
        *,
        default_labels: list[str] | None = None,
        default_assignee: str = "",
        confirmations: ConfirmationService | None = None,
    ) -> None:
        self.service = service
        self.operations = operations
        self.default_labels = default_labels or []
        self.default_assignee = default_assignee
        self.confirmations = confirmations

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = CreateIssueArgs.model_validate(args)
        labels = values.labels if values.labels is not None else self.default_labels
        confirmation_arguments = {
            "title": values.title,
            "body": values.body,
            "labels": labels,
            "assignee": values.assignee or self.default_assignee or None,
        }
        high_risk = self._is_high_risk(values.title, labels)
        if high_risk and self.confirmations:
            if not values.confirmation_code:
                code = await self.confirmations.issue(
                    context=context,
                    tool_name=self.name,
                    arguments=confirmation_arguments,
                )
                return ToolResponse(
                    tool_name=self.name,
                    success=True,
                    llm_content=(
                        "高风险操作尚未执行。请用户明确确认后，使用完全相同的参数并传入 "
                        f"confirmation_code={code} 再次调用。确认码 10 分钟内有效。"
                    ),
                    display_data={
                        "status": "pending_confirmation",
                        "confirmation_code": code,
                    },
                )
            confirmed, reason = await self.confirmations.consume(
                context=context,
                tool_name=self.name,
                arguments=confirmation_arguments,
                code=values.confirmation_code,
            )
            if not confirmed:
                return ToolResponse(
                    tool_name=self.name,
                    success=False,
                    llm_content=reason,
                    error="confirmation required",
                )
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
                labels=labels,
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

    @staticmethod
    def _is_high_risk(title: str, labels: list[str]) -> bool:
        normalized_labels = {label.strip().upper() for label in labels}
        normalized_title = title.strip().upper()
        return bool(normalized_labels.intersection({"P0", "P1"})) or normalized_title.startswith(("[P0]", "[P1]"))


class GitHubRecentChangesTool(Tool):
    name = "github_recent_changes"
    description = (
        "List recent commits and pull requests from the configured repository. "
        "Use this when the user asks what changed recently, for recent commits, or for PR updates."
    )
    args_model = RecentChangesArgs
    retryable = True

    def __init__(self, service: GitHubService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = RecentChangesArgs.model_validate(args)
        changes = await self.service.recent_changes(limit=values.limit)
        data = [change.model_dump() for change in changes]
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data={"changes": data},
        )
