import json

import httpx
from sqlalchemy import func, select

from app.db.models import ToolOperation
from app.db.session import create_engine, create_session_factory, create_tables
from app.llm.provider import ToolCall
from app.schemas.message import UnifiedMessage
from app.services.conversation_service import ConversationService
from app.services.github_service import (
    GitHubAuthenticationError,
    GitHubIssue,
    GitHubError,
    GitHubRateLimitError,
    GitHubService,
)
from app.services.identity_service import IdentityService
from app.services.permission_service import PermissionService
from app.services.tool_operation_service import ToolOperationService
from app.tools.context import ToolContext
from app.tools.github import GitHubCreateIssueTool
from app.tools.runner import ToolRunner


class FakeTraceService:
    def __init__(self) -> None:
        self.steps: list[dict] = []

    async def record_step(self, **kwargs) -> None:
        self.steps.append(kwargs)


class FakeGitHubService:
    def __init__(self) -> None:
        self.create_calls = 0

    async def create_issue(self, **kwargs) -> GitHubIssue:
        self.create_calls += 1
        return GitHubIssue(
            number=126,
            title=kwargs["title"],
            state="open",
            html_url="https://github.com/acme/flowagent/issues/126",
            body=kwargs["body"],
            labels=kwargs["labels"],
            assignees=[kwargs["assignee"]] if kwargs.get("assignee") else [],
        )


async def test_github_service_search_and_create_contract() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "number": 84,
                            "title": "Avatar upload fails",
                            "state": "open",
                            "html_url": "https://github.com/acme/repo/issues/84",
                            "body": "details",
                            "labels": [{"name": "bug"}],
                            "assignees": [{"login": "octocat"}],
                        },
                        {
                            "number": 85,
                            "title": "A pull request",
                            "state": "open",
                            "html_url": "https://github.com/acme/repo/pull/85",
                            "pull_request": {},
                        },
                    ]
                },
            )
        body = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "number": 126,
                "title": body["title"],
                "state": "open",
                "html_url": "https://github.com/acme/repo/issues/126",
                "body": body["body"],
                "labels": [{"name": item} for item in body["labels"]],
                "assignees": [{"login": item} for item in body["assignees"]],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GitHubService(
            token="token",
            owner="acme",
            repo="repo",
            api_version="2026-03-10",
            client=client,
        )
        issues = await service.search_issues(
            query="avatar 500", state="open", labels=["bug"]
        )
        created = await service.create_issue(
            title="Avatar upload returns 500",
            body="Steps to reproduce",
            labels=["bug"],
            assignee="octocat",
        )

    assert [issue.number for issue in issues] == [84]
    assert created.number == 126
    assert "repo%3Aacme%2Frepo" in str(requests[0].url)
    assert requests[0].headers["X-GitHub-Api-Version"] == "2026-03-10"


async def test_github_service_classifies_auth_and_rate_limit_errors() -> None:
    responses = iter(
        [
            httpx.Response(401, json={"message": "Bad credentials"}),
            httpx.Response(
                403,
                headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "99"},
                json={"message": "API rate limit exceeded"},
            ),
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GitHubService(
            token="token", owner="acme", repo="repo", client=client
        )
        try:
            await service.get_issue(1)
            raise AssertionError("expected authentication failure")
        except GitHubAuthenticationError:
            pass
        try:
            await service.get_issue(1)
            raise AssertionError("expected rate limit failure")
        except GitHubRateLimitError as exc:
            assert exc.retry_after == "99"


async def test_search_cannot_escape_configured_repository() -> None:
    service = GitHubService(token="token", owner="acme", repo="repo")
    try:
        await service.search_issues(query="bug repo:another/private")
        raise AssertionError("expected repository scope rejection")
    except GitHubError as exc:
        assert "qualifiers" in str(exc)


async def test_create_issue_rbac_and_idempotency(tmp_path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'tools.db'}")
    await create_tables(engine)
    factory = create_session_factory(engine)
    conversations = ConversationService(factory, IdentityService())
    inbound = await conversations.accept_inbound(
        UnifiedMessage(
            platform="feishu",
            tenant_id="tenant",
            external_user_id="user",
            conversation_id="chat",
            message_id="om-1",
            message_type="text",
            text="create a bug",
        )
    )
    assert inbound is not None
    fake_github = FakeGitHubService()
    operations = ToolOperationService(factory)
    tool = GitHubCreateIssueTool(
        fake_github,  # type: ignore[arg-type]
        operations,
        default_labels=["bug"],
    )
    traces = FakeTraceService()
    call = ToolCall(
        id="call-1",
        name="github_create_issue",
        arguments={"title": "Bug title", "body": "Bug details"},
    )
    base_context = dict(
        tenant_id=inbound.tenant_id,
        user_id=inbound.user_id,
        conversation_id=inbound.conversation_id,
        source_message_id=inbound.message_id,
        external_message_id="om-1",
    )
    try:
        member_runner = ToolRunner(
            trace_service=traces,  # type: ignore[arg-type]
            permission_service=PermissionService(member_can_create_issue=False),
            tools=[tool],
        )
        denied = await member_runner.run(
            call=call,
            run_id=1,
            step_no=1,
            context=ToolContext(user_role="member", **base_context),
        )
        assert denied.success is False
        assert denied.error == "permission denied"
        assert fake_github.create_calls == 0

        lead_runner = ToolRunner(
            trace_service=traces,  # type: ignore[arg-type]
            permission_service=PermissionService(),
            tools=[tool],
        )
        context = ToolContext(user_role="lead", **base_context)
        invalid = await lead_runner.run(
            call=ToolCall(
                id="invalid",
                name="github_create_issue",
                arguments={"title": "Missing body", "unexpected": True},
            ),
            run_id=1,
            step_no=2,
            context=context,
        )
        assert invalid.success is False
        assert invalid.error == "invalid tool arguments"
        assert fake_github.create_calls == 0

        first = await lead_runner.run(
            call=call, run_id=1, step_no=3, context=context
        )
        second = await lead_runner.run(
            call=call, run_id=1, step_no=4, context=context
        )

        assert first.success is True
        assert second.success is True
        assert second.display_data["idempotent_replay"] is True
        assert fake_github.create_calls == 1
        async with factory() as session:
            assert await session.scalar(select(func.count(ToolOperation.id))) == 1
    finally:
        await engine.dispose()
