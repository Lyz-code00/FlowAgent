import json

import httpx

from app.db.session import create_engine, create_session_factory, create_tables
from app.schemas.message import UnifiedMessage
from app.services.confirmation_service import ConfirmationService
from app.services.conversation_service import ConversationService
from app.services.github_service import GitHubService
from app.services.identity_service import IdentityService
from app.services.tool_operation_service import ToolOperationService
from app.tools.context import ToolContext
from app.tools.github import (
    AddIssueAttachmentsArgs,
    AttachmentLink,
    CloseIssueArgs,
    GitHubAddIssueAttachmentsTool,
    GitHubAssignIssueTool,
    GitHubCloseIssueTool,
    GitHubUpdateIssueTool,
    AssignIssueArgs,
    UpdateIssueArgs,
)


def _issue(number: int, **updates) -> dict:
    data = {
        "number": number,
        "title": "Payment bug",
        "state": "open",
        "html_url": f"https://github.example/acme/repo/issues/{number}",
        "body": "details",
        "labels": [{"name": "bug"}],
        "assignees": [],
    }
    data.update(updates)
    return data


async def test_github_issue_mutation_service_contracts() -> None:
    payloads: list[tuple[str, str, dict]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else {}
        payloads.append((request.method, request.url.path, payload))
        if request.method == "POST" and request.url.path.endswith("/comments"):
            return httpx.Response(
                201,
                json={
                    "id": 90,
                    "html_url": "https://github.example/acme/repo/issues/7#issuecomment-90",
                    "body": payload["body"],
                    "user": {"login": "flowagent"},
                    "created_at": "2026-09-14T01:00:00Z",
                },
            )
        if payload.get("state") == "closed":
            return httpx.Response(200, json=_issue(7, state="closed"))
        if "assignees" in payload:
            return httpx.Response(
                200,
                json=_issue(7, assignees=[{"login": item} for item in payload["assignees"]]),
            )
        return httpx.Response(200, json=_issue(7, title=payload.get("title", "Payment bug")))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GitHubService(token="token", owner="acme", repo="repo", client=client)
        updated = await service.update_issue(issue_number=7, title="Updated")
        assigned = await service.assign_issue(issue_number=7, assignees=["octocat"])
        closed = await service.close_issue(issue_number=7, state_reason="completed")
        comment = await service.add_issue_comment(issue_number=7, body="## 附件")

    assert updated.title == "Updated"
    assert assigned.assignees == ["octocat"]
    assert closed.state == "closed"
    assert comment.html_url.endswith("#issuecomment-90")
    assert payloads == [
        ("PATCH", "/repos/acme/repo/issues/7", {"title": "Updated"}),
        ("PATCH", "/repos/acme/repo/issues/7", {"assignees": ["octocat"]}),
        ("PATCH", "/repos/acme/repo/issues/7", {"state": "closed", "state_reason": "completed"}),
        ("POST", "/repos/acme/repo/issues/7/comments", {"body": "## 附件"}),
    ]


async def test_issue_mutation_tools_and_close_confirmation(tmp_path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'mutations.db'}")
    await create_tables(engine)
    factory = create_session_factory(engine)
    conversations = ConversationService(factory, IdentityService())
    inbound = await conversations.accept_inbound(
        UnifiedMessage(
            platform="feishu",
            tenant_id="tenant",
            external_user_id="user",
            conversation_id="chat",
            message_id="om-mutation",
            message_type="text",
            text="维护 Issue #7",
        )
    )
    assert inbound is not None
    context = ToolContext(
        tenant_id=inbound.tenant_id,
        user_id=inbound.user_id,
        user_role="lead",
        conversation_id=inbound.conversation_id,
        source_message_id=inbound.message_id,
        external_message_id="om-mutation",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if request.url.path.endswith("/comments"):
            return httpx.Response(
                201,
                json={"id": 8, "html_url": "https://github.example/issues/7#comment-8", "body": payload["body"]},
            )
        state = "closed" if payload.get("state") == "closed" else "open"
        return httpx.Response(200, json=_issue(7, state=state, assignees=[{"login": item} for item in payload.get("assignees", [])]))

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = GitHubService(token="token", owner="acme", repo="repo", client=client)
            operations = ToolOperationService(factory)
            assert (await GitHubUpdateIssueTool(service, operations).run(
                context, UpdateIssueArgs(issue_number=7, labels=["bug", "P2"])
            )).success
            assert (await GitHubAssignIssueTool(service, operations).run(
                context, AssignIssueArgs(issue_number=7, assignees=["octocat"])
            )).display_data["assignees"] == ["octocat"]
            attachment = await GitHubAddIssueAttachmentsTool(service, operations).run(
                context,
                AddIssueAttachmentsArgs(
                    issue_number=7,
                    attachments=[AttachmentLink(name="日志", url="https://files.example/log.txt")],
                ),
            )
            assert attachment.display_data["html_url"].endswith("#comment-8")

            close_tool = GitHubCloseIssueTool(
                service, operations, ConfirmationService(factory)
            )
            pending = await close_tool.run(context, CloseIssueArgs(issue_number=7))
            assert pending.display_data["status"] == "pending_confirmation"
            confirmed = await close_tool.run(
                context,
                CloseIssueArgs(
                    issue_number=7,
                    confirmation_code=pending.display_data["confirmation_code"],
                ),
            )
            assert confirmed.display_data["state"] == "closed"
    finally:
        await engine.dispose()
