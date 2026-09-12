from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Conversation, Message
from app.schemas.message import UnifiedMessage
from app.services.identity_service import IdentityService


@dataclass(frozen=True)
class StoredInbound:
    conversation_id: int
    message_id: int
    user_id: int
    tenant_id: int
    role: str


@dataclass(frozen=True)
class HistoryMessage:
    role: str
    content: str


class ConversationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        identity_service: IdentityService,
    ) -> None:
        self.session_factory = session_factory
        self.identity_service = identity_service

    async def accept_inbound(self, message: UnifiedMessage) -> StoredInbound | None:
        async with self.session_factory() as session:
            if await self._message_exists(session, message.message_id):
                return None
            try:
                identity = await self.identity_service.resolve(session, message)
                conversation = await session.scalar(
                    select(Conversation).where(
                        Conversation.tenant_id == identity.tenant_id,
                        Conversation.platform == message.platform,
                        Conversation.external_conversation_id
                        == message.conversation_id,
                    )
                )
                if conversation is None:
                    conversation = Conversation(
                        tenant_id=identity.tenant_id,
                        platform=message.platform,
                        external_conversation_id=message.conversation_id,
                    )
                    session.add(conversation)
                    await session.flush()
                conversation.updated_at = message.timestamp
                stored = Message(
                    conversation_id=conversation.id,
                    user_id=identity.user_id,
                    role="user",
                    content=message.text,
                    external_message_id=message.message_id,
                    created_at=message.timestamp,
                )
                session.add(stored)
                await session.commit()
                return StoredInbound(
                    conversation_id=conversation.id,
                    message_id=stored.id,
                    user_id=identity.user_id,
                    tenant_id=identity.tenant_id,
                    role=identity.role,
                )
            except IntegrityError:
                await session.rollback()
                if await self._message_exists(session, message.message_id):
                    return None
                raise

    async def recent_history(
        self, conversation_id: int, *, turns: int
    ) -> list[HistoryMessage]:
        limit = max(1, turns) * 2
        async with self.session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(Message)
                        .where(
                            Message.conversation_id == conversation_id,
                            Message.role.in_(("user", "assistant")),
                        )
                        .order_by(Message.id.desc())
                        .limit(limit)
                    )
                ).all()
            )
        rows.reverse()
        return [HistoryMessage(role=row.role, content=row.content) for row in rows]

    async def save_assistant(self, conversation_id: int, content: str) -> int:
        async with self.session_factory() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.updated_at = datetime.now(timezone.utc)
            message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=content,
            )
            session.add(message)
            await session.commit()
            return message.id

    @staticmethod
    async def _message_exists(session: AsyncSession, external_message_id: str) -> bool:
        return (
            await session.scalar(
                select(Message.id).where(
                    Message.external_message_id == external_message_id
                )
            )
        ) is not None
