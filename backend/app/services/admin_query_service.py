from datetime import datetime, timezone
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AgentRun,
    AgentStep,
    ChannelAccount,
    Conversation,
    Feedback,
    KnowledgeBase,
    KnowledgeDocument,
    Message,
    Tenant,
    ToolOperation,
    User,
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

    async def list_users(self) -> list[dict[str, Any]]:
        message_count = (
            select(func.count(Message.id))
            .where(Message.user_id == User.id)
            .correlate(User)
            .scalar_subquery()
        )
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(User, Tenant.external_key, message_count)
                    .join(Tenant, Tenant.id == User.tenant_id)
                    .order_by(User.id.asc())
                )
            ).all()
            user_ids = [user.id for user, _, _ in rows]
            accounts = (
                (
                    await session.scalars(
                        select(ChannelAccount)
                        .where(ChannelAccount.user_id.in_(user_ids))
                        .order_by(ChannelAccount.id.asc())
                    )
                ).all()
                if user_ids
                else []
            )
        accounts_by_user: dict[int, list[dict[str, str]]] = {}
        for account in accounts:
            accounts_by_user.setdefault(account.user_id, []).append(
                {
                    "platform": account.platform,
                    "external_user_id": account.external_user_id,
                }
            )
        return [
            {
                "id": user.id,
                "name": user.name,
                "role": user.role,
                "tenant_key": tenant_key,
                "channels": accounts_by_user.get(user.id, []),
                "message_count": int(count or 0),
                "created_at": user.created_at.isoformat(),
                "updated_at": user.updated_at.isoformat(),
            }
            for user, tenant_key, count in rows
        ]

    async def list_tenants(self) -> list[dict[str, Any]]:
        user_count = (
            select(func.count(User.id))
            .where(User.tenant_id == Tenant.id)
            .correlate(Tenant)
            .scalar_subquery()
        )
        conversation_count = (
            select(func.count(Conversation.id))
            .where(Conversation.tenant_id == Tenant.id)
            .correlate(Tenant)
            .scalar_subquery()
        )
        document_count = (
            select(func.count(KnowledgeDocument.id))
            .join(
                KnowledgeBase,
                KnowledgeBase.id == KnowledgeDocument.knowledge_base_id,
            )
            .where(KnowledgeBase.tenant_id == Tenant.id)
            .correlate(Tenant)
            .scalar_subquery()
        )
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        Tenant,
                        user_count,
                        conversation_count,
                        document_count,
                    ).order_by(Tenant.id.asc())
                )
            ).all()
        return [
            {
                "id": tenant.id,
                "external_key": tenant.external_key,
                "name": tenant.name,
                "status": tenant.status,
                "user_count": int(users or 0),
                "conversation_count": int(conversations or 0),
                "document_count": int(documents or 0),
            }
            for tenant, users, conversations, documents in rows
        ]

    async def update_user_role(
        self, user_id: int, *, role: str
    ) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.role = role
            await session.commit()
        users = await self.list_users()
        return next((item for item in users if item["id"] == user_id), None)

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
            feedback_rows = (
                (
                    await session.scalars(
                        select(Feedback).where(
                            Feedback.message_id.in_([message.id for message in messages])
                        )
                    )
                ).all()
                if messages
                else []
            )
        feedback_by_message = {
            feedback.message_id: {
                "id": feedback.id,
                "rating": feedback.rating,
                "reason": feedback.reason,
            }
            for feedback in feedback_rows
        }
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
                    "feedback": feedback_by_message.get(message.id),
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
