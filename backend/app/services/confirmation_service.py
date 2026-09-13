import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ActionConfirmation
from app.tools.context import ToolContext


class ConfirmationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        ttl_minutes: int = 10,
    ) -> None:
        self.session_factory = session_factory
        self.ttl_minutes = ttl_minutes

    async def issue(
        self, *, context: ToolContext, tool_name: str, arguments: dict[str, Any]
    ) -> str:
        code = secrets.token_hex(4).upper()
        async with self.session_factory() as session:
            session.add(
                ActionConfirmation(
                    code=code,
                    tool_name=tool_name,
                    args_hash=self.arguments_hash(arguments),
                    conversation_id=context.conversation_id,
                    user_id=context.user_id,
                    status="pending",
                    expires_at=datetime.now(timezone.utc)
                    + timedelta(minutes=self.ttl_minutes),
                )
            )
            await session.commit()
        return code

    async def consume(
        self,
        *,
        context: ToolContext,
        tool_name: str,
        arguments: dict[str, Any],
        code: str,
    ) -> tuple[bool, str]:
        async with self.session_factory() as session:
            confirmation = await session.scalar(
                select(ActionConfirmation).where(ActionConfirmation.code == code.upper())
            )
            if confirmation is None:
                return False, "确认码无效"
            expires_at = confirmation.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                confirmation.status = "expired"
                await session.commit()
                return False, "确认码已过期，请重新发起操作"
            if confirmation.status != "pending":
                return False, "确认码已使用或已失效"
            if (
                confirmation.tool_name != tool_name
                or confirmation.conversation_id != context.conversation_id
                or confirmation.user_id != context.user_id
                or confirmation.args_hash != self.arguments_hash(arguments)
            ):
                return False, "确认码与当前操作不匹配"
            confirmation.status = "consumed"
            confirmation.confirmed_at = datetime.now(timezone.utc)
            await session.commit()
            return True, "confirmed"

    @staticmethod
    def arguments_hash(arguments: dict[str, Any]) -> str:
        canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
