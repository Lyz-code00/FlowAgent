from dataclasses import dataclass
from datetime import datetime, timezone
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Conversation, ConversationSummary, InboundEventAudit, Message
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
    _URL_RE = re.compile(r"https?://[^\s<>()，。；！？]+")
    _ISSUE_RE = re.compile(r"(?:Issue\s*)?#\d+", re.IGNORECASE)
    _DURABLE_NOTE_RE = re.compile(
        r"记住|决定|要求|不要|必须|待办|负责人|截止|偏好|约定|授权|部署|P[0-3]",
        re.IGNORECASE,
    )
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
                await self._record_delivery(message, duplicate=True)
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
                    content=self._message_content_for_history(message),
                    external_message_id=message.message_id,
                    created_at=message.timestamp,
                )
                session.add(stored)
                session.add(
                    InboundEventAudit(
                        platform=message.platform,
                        external_message_id=message.message_id,
                        duplicate=False,
                    )
                )
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
                    await self._record_delivery(message, duplicate=True)
                    return None
                raise

    async def _record_delivery(
        self, message: UnifiedMessage, *, duplicate: bool
    ) -> None:
        async with self.session_factory() as audit_session:
            audit_session.add(
                InboundEventAudit(
                    platform=message.platform,
                    external_message_id=message.message_id,
                    duplicate=duplicate,
                )
            )
            await audit_session.commit()

    @staticmethod
    def _message_content_for_history(message: UnifiedMessage) -> str:
        parts = [message.text.strip()] if message.text.strip() else []
        for index, attachment in enumerate(message.attachments, 1):
            label = attachment.name or f"{attachment.type} {index}"
            if attachment.extracted_text:
                parts.append(f"【附件：{label}】\n{attachment.extracted_text[:100_000]}")
            elif attachment.data_base64:
                parts.append(f"【图片：{label}】")
            elif attachment.error:
                parts.append(f"【附件 {label} 处理失败：{attachment.error}】")
        return "\n\n".join(parts).strip() or "【空消息】"

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
            summary = await session.scalar(
                select(ConversationSummary)
                .where(ConversationSummary.conversation_id == conversation_id)
                .order_by(ConversationSummary.updated_at.desc())
                .limit(1)
            )
            oldest_recent_id = min((row.id for row in rows), default=0)
            older_rows = list(
                (
                    await session.scalars(
                        select(Message)
                        .where(
                            Message.conversation_id == conversation_id,
                            Message.id < oldest_recent_id,
                            Message.role.in_(("user", "assistant")),
                        )
                        .order_by(Message.id.desc())
                        .limit(200)
                    )
                ).all()
            )
        rows.reverse()
        memory = self._build_long_term_memory(summary, older_rows)
        history = [HistoryMessage(role=row.role, content=row.content) for row in rows]
        if memory:
            history.insert(0, HistoryMessage(role="system", content=memory))
        return history

    @classmethod
    def _build_long_term_memory(
        cls,
        summary: ConversationSummary | None,
        older_rows: list[Message],
    ) -> str:
        sections: list[str] = []
        if summary is not None:
            summary_lines = [f"历史讨论摘要（{summary.status}）：{summary.summary}"]
            if summary.decisions:
                summary_lines.append("已记录决策：" + "；".join(summary.decisions[:20]))
            if summary.bugs:
                summary_lines.append("已记录问题：" + "；".join(summary.bugs[:20]))
            if summary.action_items:
                items = []
                for action in summary.action_items[:20]:
                    title = str(action.get("title") or action.get("content") or "").strip()
                    status = str(action.get("status") or "待处理")
                    if title:
                        items.append(f"[{status}] {title}")
                if items:
                    summary_lines.append("已记录待办：" + "；".join(items))
            sections.append("\n".join(summary_lines))

        anchors: list[str] = []
        seen: set[str] = set()
        for row in older_rows:
            found = cls._URL_RE.findall(row.content) + cls._ISSUE_RE.findall(row.content)
            for anchor in found:
                cleaned = anchor.rstrip(".,;:)]}")
                if cleaned not in seen:
                    seen.add(cleaned)
                    anchors.append(cleaned)
                if len(anchors) >= 30:
                    break
            if len(anchors) >= 30:
                break
        if anchors:
            sections.append("历史持久引用（需要实时性时重新验证）：\n" + "\n".join(anchors))
        durable_notes: list[str] = []
        note_seen: set[str] = set()
        for row in older_rows:
            compact = " ".join(row.content.split())
            if not compact or not cls._DURABLE_NOTE_RE.search(compact):
                continue
            note = f"{row.role}: {compact[:500]}"
            if note not in note_seen:
                note_seen.add(note)
                durable_notes.append(note)
            if len(durable_notes) >= 20:
                break
        if durable_notes:
            sections.append(
                "历史约束与事项摘录（可能已过期，需结合当前对话判断）：\n"
                + "\n".join(reversed(durable_notes))
            )
        if not sections:
            return ""
        return "【FlowAgent 长期记忆】\n" + "\n\n".join(sections)

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
