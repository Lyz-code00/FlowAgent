from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
    return {
        "environment": settings.env,
        "llm": {
            "model": agent_config.model,
            "configured": bool(settings.llm_api_key),
            "max_steps": agent_config.max_steps,
            "context_turns": settings.context_turns,
        },
        "github": {
            "owner": settings.github_owner,
            "repo": settings.github_repo,
            "configured": bool(
                settings.github_token and settings.github_owner and settings.github_repo
            ),
            "default_labels": settings.github_default_labels,
            "default_assignee": settings.github_default_assignee or None,
            "member_can_create_issue": settings.member_can_create_issue,
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


@router.get("/conversations/{conversation_id}/traces")
async def conversation_traces(conversation_id: int, request: Request) -> list[dict]:
    return await request.app.state.admin_query_service.conversation_traces(
        conversation_id
    )
