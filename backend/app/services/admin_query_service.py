from datetime import datetime, timezone
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AgentRun,
    AgentStep,
    Conversation,
    Message,
    Tenant,
    ToolOperation,
)


class AdminQueryService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def dashboard_metrics(self) -> dict[str, int | float]:
        today = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        async with self.session_factory() as session:
            conversations = await session.scalar(
                select(func.count(distinct(Message.conversation_id))).where(
                    Message.created_at >= today
                )
            )
            agent_runs = await session.scalar(
                select(func.count(AgentRun.id)).where(AgentRun.started_at >= today)
            )
            tool_calls = await session.scalar(
                select(func.count(AgentStep.id)).where(
                    AgentStep.kind == "tool", AgentStep.created_at >= today
                )
            )
            issues_created = await session.scalar(
                select(func.count(ToolOperation.id)).where(
                    ToolOperation.tool_name == "github_create_issue",
                    ToolOperation.status == "succeeded",
                    ToolOperation.created_at >= today,
                )
            )
            knowledge_searches = await session.scalar(
                select(func.count(AgentStep.id)).where(
                    AgentStep.kind == "tool",
                    AgentStep.name == "knowledge_search",
                    AgentStep.created_at >= today,
                )
            )
            failed_calls = await session.scalar(
                select(func.count(AgentStep.id)).where(
                    AgentStep.status == "failed", AgentStep.created_at >= today
                )
            )
            average_latency = await session.scalar(
                select(func.avg(AgentRun.latency_ms)).where(
                    AgentRun.started_at >= today,
                    AgentRun.latency_ms.is_not(None),
                )
            )
        return {
            "conversations_today": int(conversations or 0),
            "agent_runs_today": int(agent_runs or 0),
            "tool_calls_today": int(tool_calls or 0),
            "github_issues_created_today": int(issues_created or 0),
            "knowledge_searches_today": int(knowledge_searches or 0),
            "failed_calls_today": int(failed_calls or 0),
            "average_response_ms": round(float(average_latency or 0), 2),
        }

    async def list_conversations(
        self, *, tenant_key: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        last_message = (
            select(Message.content)
            .where(Message.conversation_id == Conversation.id)
            .order_by(Message.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        message_count = (
            select(func.count(Message.id))
            .where(Message.conversation_id == Conversation.id)
            .scalar_subquery()
        )
        statement = (
            select(Conversation, Tenant.external_key, last_message, message_count)
            .join(Tenant, Tenant.id == Conversation.tenant_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .offset(offset)
            .limit(limit)
        )
        if tenant_key:
            statement = statement.where(Tenant.external_key == tenant_key)
        async with self.session_factory() as session:
            rows = (await session.execute(statement)).all()
        return [
            {
                "id": conversation.id,
                "tenant_key": external_key,
                "platform": conversation.platform,
                "external_conversation_id": conversation.external_conversation_id,
                "message_count": int(count or 0),
                "last_message": content,
                "updated_at": conversation.updated_at.isoformat(),
            }
            for conversation, external_key, content, count in rows
        ]

    async def conversation_detail(self, conversation_id: int) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(Conversation, Tenant.external_key)
                    .join(Tenant, Tenant.id == Conversation.tenant_id)
                    .where(Conversation.id == conversation_id)
                )
            ).one_or_none()
            if row is None:
                return None
            conversation, tenant_key = row
            messages = (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.id.asc())
                )
            ).all()
        return {
            "id": conversation.id,
            "tenant_key": tenant_key,
            "platform": conversation.platform,
            "external_conversation_id": conversation.external_conversation_id,
            "messages": [
                {
                    "id": message.id,
                    "role": message.role,
                    "content": message.content,
                    "external_message_id": message.external_message_id,
                    "created_at": message.created_at.isoformat(),
                }
                for message in messages
            ],
        }

    async def conversation_traces(self, conversation_id: int) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            runs = (
                await session.scalars(
                    select(AgentRun)
                    .where(AgentRun.conversation_id == conversation_id)
                    .order_by(AgentRun.id.desc())
                )
            ).all()
            result: list[dict[str, Any]] = []
            for run in runs:
                steps = (
                    await session.scalars(
                        select(AgentStep)
                        .where(AgentStep.run_id == run.id)
                        .order_by(AgentStep.step_no.asc(), AgentStep.id.asc())
                    )
                ).all()
                result.append(
                    {
                        "id": run.id,
                        "model": run.model,
                        "status": run.status,
                        "latency_ms": run.latency_ms,
                        "final_answer": run.final_answer,
                        "error": run.error,
                        "started_at": run.started_at.isoformat(),
                        "completed_at": run.completed_at.isoformat()
                        if run.completed_at
                        else None,
                        "steps": [
                            {
                                "id": step.id,
                                "step_no": step.step_no,
                                "kind": step.kind,
                                "name": step.name,
                                "status": step.status,
                                "input": step.input_data,
                                "output": step.output_data,
                                "latency_ms": step.latency_ms,
                                "error": step.error,
                            }
                            for step in steps
                        ],
                    }
                )
        return result
