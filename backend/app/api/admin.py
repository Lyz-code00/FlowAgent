import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.security import require_admin

router = APIRouter(
    prefix="/api/v1",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


class UserRoleUpdate(BaseModel):
    role: Literal["member", "lead", "admin"]


class AgentConfigUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(min_length=20, max_length=20_000)
    max_steps: int = Field(ge=1, le=10)
    knowledge_enabled: bool
    github_enabled: bool


class GitHubConfigUpdate(BaseModel):
    owner: str = Field(min_length=1, max_length=255)
    repo: str = Field(min_length=1, max_length=255)
    token: str | None = Field(default=None, max_length=512)
    clear_token: bool = False
    default_labels: list[str] = Field(default_factory=list, max_length=10)
    default_assignee: str = Field(default="", max_length=255)
    member_can_create_issue: bool = False


class SummaryActionItem(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    owner: str | None = Field(default=None, max_length=255)
    due_date: str | None = Field(default=None, max_length=100)
    priority: str | None = Field(default=None, max_length=32)
    status: str = Field(default="pending", max_length=32)
    github_issue: dict | None = None


class ConversationSummaryUpdate(BaseModel):
    summary: str = Field(min_length=1, max_length=10_000)
    decisions: list[str] = Field(default_factory=list, max_length=50)
    bugs: list[str] = Field(default_factory=list, max_length=50)
    action_items: list[SummaryActionItem] = Field(default_factory=list, max_length=100)


class FeedbackUpdate(BaseModel):
    rating: Literal["positive", "negative"]
    reason: str | None = Field(default=None, max_length=2000)


class OwnershipCreate(BaseModel):
    tenant_id: int = Field(ge=1)
    service: str = Field(min_length=1, max_length=255)
    team: str = Field(default="", max_length=255)
    display_name: str = Field(default="", max_length=255)
    feishu_open_id: str = Field(default="", max_length=255)
    github_username: str = Field(default="", max_length=255)
    active: bool = True


class OwnershipUpdate(BaseModel):
    service: str = Field(min_length=1, max_length=255)
    team: str = Field(default="", max_length=255)
    display_name: str = Field(default="", max_length=255)
    feishu_open_id: str = Field(default="", max_length=255)
    github_username: str = Field(default="", max_length=255)
    active: bool = True


def serialize_agent_config(config) -> dict:
    return {
        "name": config.name,
        "model": config.model,
        "system_prompt": config.system_prompt,
        "max_steps": config.max_steps,
        "knowledge_enabled": config.knowledge_enabled,
        "github_enabled": config.github_enabled,
    }


@router.get("/dashboard/metrics")
async def dashboard_metrics(request: Request) -> dict:
    return await request.app.state.admin_query_service.dashboard_metrics()


@router.get("/users")
async def list_users(request: Request) -> list[dict]:
    return await request.app.state.admin_query_service.list_users()


@router.get("/tenants")
async def list_tenants(request: Request) -> list[dict]:
    return await request.app.state.admin_query_service.list_tenants()


@router.get("/ownership")
async def list_ownership(
    request: Request,
    tenant_key: str | None = Query(default=None, max_length=128),
) -> list[dict]:
    return await request.app.state.ownership_service.list_all(tenant_key=tenant_key)


@router.post("/ownership")
async def create_ownership(payload: OwnershipCreate, request: Request) -> dict:
    try:
        return await request.app.state.ownership_service.create(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=409, detail="该租户已存在相同服务的负责人映射"
        ) from exc


@router.put("/ownership/{mapping_id}")
async def update_ownership(
    mapping_id: int, payload: OwnershipUpdate, request: Request
) -> dict:
    try:
        result = await request.app.state.ownership_service.update(
            mapping_id, **payload.model_dump()
        )
    except Exception as exc:
        raise HTTPException(
            status_code=409, detail="负责人映射与现有服务冲突"
        ) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="ownership mapping not found")
    return result


@router.delete("/ownership/{mapping_id}")
async def delete_ownership(mapping_id: int, request: Request) -> dict:
    if not await request.app.state.ownership_service.delete(mapping_id):
        raise HTTPException(status_code=404, detail="ownership mapping not found")
    return {"deleted": True}


@router.get("/incidents")
async def list_incidents(
    request: Request, limit: int = Query(default=100, ge=1, le=500)
) -> list[dict]:
    return await request.app.state.incident_service.list_all(limit=limit)


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: int, payload: UserRoleUpdate, request: Request
) -> dict:
    user = await request.app.state.admin_query_service.update_user_role(
        user_id, role=payload.role
    )
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user


@router.get("/config/runtime")
async def runtime_config(request: Request) -> dict:
    settings = request.app.state.settings
    agent_config = await request.app.state.agent_config_service.get()
    github_config = await request.app.state.github_config_service.get()
    return {
        "environment": settings.env,
        "llm": {
            "model": agent_config.model,
            "configured": bool(settings.llm_api_key),
            "max_steps": agent_config.max_steps,
            "context_turns": settings.context_turns,
        },
        "github": {
            "owner": github_config.owner,
            "repo": github_config.repo,
            "configured": github_config.configured,
            "default_labels": github_config.default_labels,
            "default_assignee": github_config.default_assignee or None,
            "member_can_create_issue": github_config.member_can_create_issue,
        },
        "knowledge": {
            "embedding_model": settings.embedding_model,
            "external_embedding_configured": bool(settings.embedding_api_key),
            "dimensions": settings.embedding_dimensions,
            "default_top_k": settings.knowledge_top_k,
        },
        "feishu": {
            "configured": bool(settings.feishu_app_id and settings.feishu_app_secret)
        },
        "monitoring": request.app.state.observability_service.capabilities(),
    }


@router.get("/agent/config")
async def get_agent_config(request: Request) -> dict:
    return serialize_agent_config(await request.app.state.agent_config_service.get())


@router.put("/agent/config")
async def update_agent_config(
    payload: AgentConfigUpdate, request: Request
) -> dict:
    config = await request.app.state.agent_config_service.update(
        **payload.model_dump()
    )
    return serialize_agent_config(config)


@router.get("/github/config")
async def get_github_config(request: Request) -> dict:
    return await request.app.state.github_config_service.public()


@router.put("/github/config")
async def update_github_config(
    payload: GitHubConfigUpdate, request: Request
) -> dict:
    labels = list(dict.fromkeys(label.strip() for label in payload.default_labels if label.strip()))
    return await request.app.state.github_config_service.update(
        owner=payload.owner.strip(),
        repo=payload.repo.strip(),
        token=payload.token.strip() if payload.token else None,
        clear_token=payload.clear_token,
        default_labels=labels,
        default_assignee=payload.default_assignee.strip(),
        member_can_create_issue=payload.member_can_create_issue,
    )


@router.post("/github/config/test")
async def test_github_connection(request: Request) -> dict:
    try:
        service = await request.app.state.github_service_resolver()
        return await service.check_connection()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="GitHub 连接测试失败") from exc


@router.get("/summaries")
async def list_summaries(
    request: Request,
    tenant_key: str | None = Query(default=None, max_length=128),
) -> list[dict]:
    return await request.app.state.summary_service.list(tenant_key=tenant_key)


@router.put("/summaries/{summary_id}")
async def update_summary(
    summary_id: int, payload: ConversationSummaryUpdate, request: Request
) -> dict:
    summary = await request.app.state.summary_service.update(
        summary_id, **payload.model_dump()
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="summary not found")
    return summary


@router.post("/summaries/{summary_id}/confirm")
async def confirm_summary(summary_id: int, request: Request) -> dict:
    summary = await request.app.state.summary_service.confirm(summary_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="summary not found")
    return summary


@router.post("/summaries/{summary_id}/actions/{action_index}/github-issue")
async def summary_action_to_github_issue(
    summary_id: int, action_index: int, request: Request
) -> dict:
    try:
        conversion = await request.app.state.summary_service.action_for_conversion(
            summary_id, action_index
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if conversion is None:
        raise HTTPException(status_code=404, detail="summary not found")

    action = conversion["action"]
    if action.get("github_issue"):
        return action["github_issue"]

    from app.tools.context import ToolContext

    operation_name = f"summary_action_to_issue:{summary_id}:{action_index}"
    context = ToolContext(
        tenant_id=conversion["tenant_id"],
        user_id=conversion["user_id"],
        user_role="admin",
        conversation_id=conversion["conversation_id"],
        source_message_id=conversion["source_message_id"],
        external_message_id=f"summary-{summary_id}-action-{action_index}",
    )
    operations = request.app.state.tool_operation_service
    claim = await operations.claim(context=context, tool_name=operation_name)
    if not claim.should_execute:
        if claim.status == "succeeded" and claim.result_data:
            await request.app.state.summary_service.attach_issue(
                summary_id, action_index, claim.result_data
            )
            return claim.result_data
        raise HTTPException(status_code=409, detail="issue creation is already in progress")

    priority = (action.get("priority") or "").strip()
    title = str(action["content"]).strip()
    if priority and not title.lower().startswith(priority.lower()):
        title = f"[{priority}] {title}"
    title = title[:256]
    body = "\n".join(
        [
            "## 待办事项",
            str(action["content"]),
            "",
            "## 来源讨论摘要",
            conversion["summary"],
            "",
            f"- 负责人：{action.get('owner') or '未指定'}",
            f"- 截止时间：{action.get('due_date') or '未指定'}",
            f"- 优先级：{priority or '未指定'}",
            f"- FlowAgent Summary：#{summary_id}",
        ]
    )
    try:
        github_config = await request.app.state.github_config_service.get()
        github_service = await request.app.state.github_service_resolver()
        issue = await github_service.create_issue(
            title=title,
            body=body,
            labels=github_config.default_labels,
            assignee=github_config.default_assignee or None,
        )
        result = issue.model_dump()
        await operations.succeed(
            context=context,
            tool_name=operation_name,
            external_id=str(issue.number),
            result_data=result,
        )
        await request.app.state.summary_service.attach_issue(
            summary_id, action_index, result
        )
        return result
    except Exception as exc:
        await operations.fail(context=context, tool_name=operation_name, error=str(exc))
        raise HTTPException(status_code=502, detail="GitHub Issue 创建失败") from exc


@router.get("/conversations")
async def list_conversations(
    request: Request,
    tenant_key: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    return await request.app.state.admin_query_service.list_conversations(
        tenant_key=tenant_key, limit=limit, offset=offset
    )


@router.get("/conversations/{conversation_id}")
async def conversation_detail(conversation_id: int, request: Request) -> dict:
    detail = await request.app.state.admin_query_service.conversation_detail(
        conversation_id
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return detail


@router.put("/messages/{message_id}/feedback")
async def update_message_feedback(
    message_id: int, payload: FeedbackUpdate, request: Request
) -> dict:
    try:
        feedback = await request.app.state.feedback_service.upsert(
            message_id,
            rating=payload.rating,
            reason=payload.reason.strip() if payload.reason else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if feedback is None:
        raise HTTPException(status_code=404, detail="message not found")
    return feedback


@router.get("/feedback")
async def list_feedback(
    request: Request,
    rating: Literal["positive", "negative"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    return await request.app.state.feedback_service.list(rating=rating, limit=limit)


@router.get("/conversations/{conversation_id}/traces")
async def conversation_traces(conversation_id: int, request: Request) -> list[dict]:
    return await request.app.state.admin_query_service.conversation_traces(
        conversation_id
    )


@router.get("/conversations/{conversation_id}/traces/stream")
async def conversation_trace_stream(
    conversation_id: int,
    request: Request,
    once: bool = Query(default=False),
) -> StreamingResponse:
    async def events():
        previous = ""
        heartbeat = 0
        while not await request.is_disconnected():
            traces = await request.app.state.admin_query_service.conversation_traces(
                conversation_id
            )
            payload = json.dumps(traces, ensure_ascii=False, separators=(",", ":"))
            if payload != previous:
                yield f"event: traces\ndata: {payload}\n\n"
                previous = payload
            elif heartbeat % 15 == 0:
                yield ": keep-alive\n\n"
            if once:
                break
            heartbeat += 1
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
