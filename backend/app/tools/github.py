import json
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

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


class GetFileArgs(StrictToolArgs):
    path: str = Field(min_length=1, max_length=1000)
    ref: str | None = Field(default=None, min_length=1, max_length=255)
    max_chars: int = Field(default=50_000, ge=1_000, le=100_000)


class GetCommitArgs(StrictToolArgs):
    ref: str = Field(min_length=1, max_length=255)
    max_files: int = Field(default=20, ge=1, le=100)


class GetPullRequestChangesArgs(StrictToolArgs):
    pull_number: int = Field(ge=1)
    max_files: int = Field(default=30, ge=1, le=100)


class CompareArgs(StrictToolArgs):
    base: str = Field(min_length=1, max_length=255)
    head: str = Field(min_length=1, max_length=255)
    max_files: int = Field(default=30, ge=1, le=100)


class ListReleasesArgs(StrictToolArgs):
    limit: int = Field(default=10, ge=1, le=20)


class UpdateIssueArgs(StrictToolArgs):
    issue_number: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=256)
    body: str | None = Field(default=None, min_length=1, max_length=65536)
    labels: list[str] | None = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def require_change(self):
        if self.title is None and self.body is None and self.labels is None:
            raise ValueError("at least one field must be updated")
        return self


class CloseIssueArgs(StrictToolArgs):
    issue_number: int = Field(ge=1)
    state_reason: Literal["completed", "not_planned"] = "completed"
    confirmation_code: str | None = Field(default=None, min_length=8, max_length=16)


class AssignIssueArgs(StrictToolArgs):
    issue_number: int = Field(ge=1)
    assignees: list[str] = Field(max_length=10)


class AttachmentLink(StrictToolArgs):
    name: str = Field(min_length=1, max_length=255)
    url: HttpUrl


class AddIssueAttachmentsArgs(StrictToolArgs):
    issue_number: int = Field(ge=1)
    attachments: list[AttachmentLink] = Field(min_length=1, max_length=10)
    note: str | None = Field(default=None, max_length=5000)


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


class GitHubGetFileTool(Tool):
    name = "github_get_file"
    description = (
        "Read the exact UTF-8 text content of one file from the configured GitHub "
        "repository at an optional branch, tag, or commit ref. Use this when code or "
        "configuration content is needed; do not guess file contents from commit titles."
    )
    args_model = GetFileArgs
    retryable = True

    def __init__(self, service: GitHubService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = GetFileArgs.model_validate(args)
        result = await self.service.get_file(
            path=values.path, ref=values.ref, max_chars=values.max_chars
        )
        data = result.model_dump()
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data=data,
        )


class GitHubGetCommitTool(Tool):
    name = "github_get_commit"
    description = (
        "Read one GitHub commit with changed files, additions/deletions, links, and "
        "line-level patches. Use this to inspect what code a commit actually changed."
    )
    args_model = GetCommitArgs
    retryable = True

    def __init__(self, service: GitHubService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = GetCommitArgs.model_validate(args)
        result = await self.service.get_commit(
            ref=values.ref, max_files=values.max_files
        )
        data = result.model_dump()
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data=data,
        )


class GitHubGetPullRequestChangesTool(Tool):
    name = "github_get_pull_request_changes"
    description = (
        "Read a pull request and its changed files with line-level patches. Use this "
        "for PR review, regression analysis, and checking whether a proposed change "
        "could explain an incident."
    )
    args_model = GetPullRequestChangesArgs
    retryable = True

    def __init__(self, service: GitHubService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = GetPullRequestChangesArgs.model_validate(args)
        result = await self.service.get_pull_request_changes(
            pull_number=values.pull_number, max_files=values.max_files
        )
        data = result.model_dump()
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data=data,
        )


class GitHubCompareTool(Tool):
    name = "github_compare"
    description = (
        "Compare two GitHub branches, tags, or commit refs and return changed files "
        "with line-level patches. Use when the user asks what changed between versions."
    )
    args_model = CompareArgs
    retryable = True

    def __init__(self, service: GitHubService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = CompareArgs.model_validate(args)
        result = await self.service.compare(
            base=values.base, head=values.head, max_files=values.max_files
        )
        data = result.model_dump()
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data=data,
        )


class GitHubListReleasesTool(Tool):
    name = "github_list_releases"
    description = (
        "List recent GitHub releases with tags, target refs, release notes, authors, "
        "publication times, and verified release URLs."
    )
    args_model = ListReleasesArgs
    retryable = True

    def __init__(self, service: GitHubService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = ListReleasesArgs.model_validate(args)
        releases = await self.service.list_releases(limit=values.limit)
        data = [release.model_dump() for release in releases]
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data={"releases": data},
        )


class GitHubUpdateIssueTool(Tool):
    name = "github_update_issue"
    description = "Update the title, body, or labels of an existing GitHub Issue."
    permission = "github_issue_write"
    args_model = UpdateIssueArgs

    def __init__(self, service: GitHubService, operations: ToolOperationService) -> None:
        self.service = service
        self.operations = operations

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = UpdateIssueArgs.model_validate(args)
        claim = await self.operations.claim(context=context, tool_name=self.name)
        if not claim.should_execute:
            return self._replay_or_busy(claim)
        try:
            issue = await self.service.update_issue(**values.model_dump())
            data = issue.model_dump()
            await self.operations.succeed(
                context=context,
                tool_name=self.name,
                external_id=str(issue.number),
                result_data=data,
            )
        except Exception as exc:
            await self.operations.fail(context=context, tool_name=self.name, error=str(exc))
            raise
        return ToolResponse(tool_name=self.name, success=True, llm_content=json.dumps(data, ensure_ascii=False), display_data=data)

    def _replay_or_busy(self, claim) -> ToolResponse:
        if claim.status == "succeeded" and claim.result_data:
            return ToolResponse(tool_name=self.name, success=True, llm_content=json.dumps(claim.result_data, ensure_ascii=False), display_data={**claim.result_data, "idempotent_replay": True})
        return ToolResponse(tool_name=self.name, success=False, llm_content="The same update operation is already in progress.", error="operation already in progress")


class GitHubCloseIssueTool(Tool):
    name = "github_close_issue"
    description = (
        "Close an existing GitHub Issue. This always requires a second explicit user "
        "confirmation using the returned confirmation code."
    )
    permission = "github_issue_write"
    args_model = CloseIssueArgs

    def __init__(
        self,
        service: GitHubService,
        operations: ToolOperationService,
        confirmations: ConfirmationService,
    ) -> None:
        self.service = service
        self.operations = operations
        self.confirmations = confirmations

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = CloseIssueArgs.model_validate(args)
        confirmation_arguments = {
            "issue_number": values.issue_number,
            "state_reason": values.state_reason,
        }
        if not values.confirmation_code:
            code = await self.confirmations.issue(
                context=context, tool_name=self.name, arguments=confirmation_arguments
            )
            return ToolResponse(
                tool_name=self.name,
                success=True,
                llm_content=(
                    "关闭 Issue 尚未执行。请用户明确确认后，使用完全相同参数并传入 "
                    f"confirmation_code={code} 再次调用。确认码 10 分钟内有效。"
                ),
                display_data={"status": "pending_confirmation", "confirmation_code": code},
            )
        confirmed, reason = await self.confirmations.consume(
            context=context,
            tool_name=self.name,
            arguments=confirmation_arguments,
            code=values.confirmation_code,
        )
        if not confirmed:
            return ToolResponse(tool_name=self.name, success=False, llm_content=reason, error="confirmation required")
        claim = await self.operations.claim(context=context, tool_name=self.name)
        if not claim.should_execute:
            if claim.status == "succeeded" and claim.result_data:
                return ToolResponse(tool_name=self.name, success=True, llm_content=json.dumps(claim.result_data, ensure_ascii=False), display_data={**claim.result_data, "idempotent_replay": True})
            return ToolResponse(tool_name=self.name, success=False, llm_content="The same close operation is already in progress.", error="operation already in progress")
        try:
            issue = await self.service.close_issue(
                issue_number=values.issue_number, state_reason=values.state_reason
            )
            data = issue.model_dump()
            await self.operations.succeed(context=context, tool_name=self.name, external_id=str(issue.number), result_data=data)
        except Exception as exc:
            await self.operations.fail(context=context, tool_name=self.name, error=str(exc))
            raise
        return ToolResponse(tool_name=self.name, success=True, llm_content=json.dumps(data, ensure_ascii=False), display_data=data)


class GitHubAssignIssueTool(Tool):
    name = "github_assign_issue"
    description = (
        "Replace all assignees on an existing GitHub Issue. Pass an empty list to "
        "remove assignment; use owner_lookup first for role-based owner names."
    )
    permission = "github_issue_write"
    args_model = AssignIssueArgs

    def __init__(self, service: GitHubService, operations: ToolOperationService) -> None:
        self.service = service
        self.operations = operations

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = AssignIssueArgs.model_validate(args)
        claim = await self.operations.claim(context=context, tool_name=self.name)
        if not claim.should_execute:
            if claim.status == "succeeded" and claim.result_data:
                return ToolResponse(tool_name=self.name, success=True, llm_content=json.dumps(claim.result_data, ensure_ascii=False), display_data={**claim.result_data, "idempotent_replay": True})
            return ToolResponse(tool_name=self.name, success=False, llm_content="The same assignment operation is already in progress.", error="operation already in progress")
        try:
            issue = await self.service.assign_issue(
                issue_number=values.issue_number, assignees=values.assignees
            )
            data = issue.model_dump()
            await self.operations.succeed(context=context, tool_name=self.name, external_id=str(issue.number), result_data=data)
        except Exception as exc:
            await self.operations.fail(context=context, tool_name=self.name, error=str(exc))
            raise
        return ToolResponse(tool_name=self.name, success=True, llm_content=json.dumps(data, ensure_ascii=False), display_data=data)


class GitHubAddIssueAttachmentsTool(Tool):
    name = "github_add_issue_attachments"
    description = (
        "Attach auditable HTTPS file references to an Issue as a GitHub comment. "
        "This supports links only; it does not upload binary files to GitHub."
    )
    permission = "github_issue_write"
    args_model = AddIssueAttachmentsArgs

    def __init__(self, service: GitHubService, operations: ToolOperationService) -> None:
        self.service = service
        self.operations = operations

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = AddIssueAttachmentsArgs.model_validate(args)
        claim = await self.operations.claim(context=context, tool_name=self.name)
        if not claim.should_execute:
            if claim.status == "succeeded" and claim.result_data:
                return ToolResponse(tool_name=self.name, success=True, llm_content=json.dumps(claim.result_data, ensure_ascii=False), display_data={**claim.result_data, "idempotent_replay": True})
            return ToolResponse(tool_name=self.name, success=False, llm_content="The same attachment operation is already in progress.", error="operation already in progress")
        lines = ["## 附件"]
        for attachment in values.attachments:
            lines.append(f"- [{attachment.name}]({attachment.url})")
        if values.note:
            lines.extend(["", values.note])
        try:
            comment = await self.service.add_issue_comment(
                issue_number=values.issue_number, body="\n".join(lines)
            )
            data = {**comment.model_dump(), "issue_number": values.issue_number}
            await self.operations.succeed(context=context, tool_name=self.name, external_id=str(comment.id), result_data=data)
        except Exception as exc:
            await self.operations.fail(context=context, tool_name=self.name, error=str(exc))
            raise
        return ToolResponse(tool_name=self.name, success=True, llm_content=json.dumps(data, ensure_ascii=False), display_data=data)
