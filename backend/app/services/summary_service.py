from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Conversation, ConversationSummary, Tenant
from app.tools.context import ToolContext


class SummaryService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def save(
        self,
        *,
        context: ToolContext,
        summary: str,
        decisions: list[str],
        bugs: list[str],
        action_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(ConversationSummary).where(
                    ConversationSummary.source_message_id == context.source_message_id
                )
            )
            if row is None:
                row = ConversationSummary(
                    tenant_id=context.tenant_id,
                    conversation_id=context.conversation_id,
                    source_message_id=context.source_message_id,
                    created_by_user_id=context.user_id,
                    summary=summary,
                    decisions=decisions,
                    bugs=bugs,
                    action_items=action_items,
                )
                session.add(row)
            else:
                row.summary = summary
                row.decisions = decisions
                row.bugs = bugs
                row.action_items = action_items
            await session.commit()
            await session.refresh(row)
            return self._serialize(row)

    async def list(self, *, tenant_key: str | None = None) -> list[dict[str, Any]]:
        statement = (
            select(ConversationSummary, Tenant.external_key, Conversation.external_conversation_id)
            .join(Tenant, Tenant.id == ConversationSummary.tenant_id)
            .join(Conversation, Conversation.id == ConversationSummary.conversation_id)
            .order_by(ConversationSummary.updated_at.desc())
        )
        if tenant_key:
            statement = statement.where(Tenant.external_key == tenant_key)
        async with self.session_factory() as session:
            rows = (await session.execute(statement)).all()
        return [
            {
                **self._serialize(item),
                "tenant_key": key,
                "external_conversation_id": external_id,
            }
            for item, key, external_id in rows
        ]

    async def update(
        self,
        summary_id: int,
        *,
        summary: str,
        decisions: list[str],
        bugs: list[str],
        action_items: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            row = await session.get(ConversationSummary, summary_id)
            if row is None:
                return None
            row.summary = summary
            row.decisions = decisions
            row.bugs = bugs
            row.action_items = action_items
            await session.commit()
            await session.refresh(row)
            return self._serialize(row)

    @staticmethod
    def _serialize(row: ConversationSummary) -> dict[str, Any]:
        return {
            "id": row.id,
            "conversation_id": row.conversation_id,
            "summary": row.summary,
            "decisions": row.decisions,
            "bugs": row.bugs,
            "action_items": row.action_items,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }
