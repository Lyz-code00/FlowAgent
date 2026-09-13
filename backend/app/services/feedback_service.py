from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Conversation, Feedback, Message, Tenant


class FeedbackService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def upsert(
        self, message_id: int, *, rating: str, reason: str | None
    ) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            message = await session.get(Message, message_id)
            if message is None:
                return None
            if message.role != "assistant":
                raise ValueError("only assistant messages can receive feedback")
            feedback = await session.scalar(
                select(Feedback).where(Feedback.message_id == message_id)
            )
            if feedback is None:
                feedback = Feedback(message_id=message_id, rating=rating, reason=reason)
                session.add(feedback)
            else:
                feedback.rating = rating
                feedback.reason = reason
            await session.commit()
            await session.refresh(feedback)
            return self._serialize(feedback)

    async def list(
        self, *, rating: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        statement = (
            select(Feedback, Message, Conversation, Tenant.external_key)
            .join(Message, Message.id == Feedback.message_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .join(Tenant, Tenant.id == Conversation.tenant_id)
            .order_by(Feedback.updated_at.desc(), Feedback.id.desc())
            .limit(limit)
        )
        if rating:
            statement = statement.where(Feedback.rating == rating)
        async with self.session_factory() as session:
            rows = (await session.execute(statement)).all()
        return [
            {
                **self._serialize(feedback),
                "content": message.content,
                "conversation_id": conversation.id,
                "tenant_key": tenant_key,
                "platform": conversation.platform,
            }
            for feedback, message, conversation, tenant_key in rows
        ]

    @staticmethod
    def _serialize(feedback: Feedback) -> dict[str, Any]:
        return {
            "id": feedback.id,
            "message_id": feedback.message_id,
            "rating": feedback.rating,
            "reason": feedback.reason,
            "created_at": feedback.created_at.isoformat(),
            "updated_at": feedback.updated_at.isoformat(),
        }
