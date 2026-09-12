from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ToolOperation
from app.tools.context import ToolContext


@dataclass(frozen=True)
class OperationClaim:
    should_execute: bool
    status: str
    result_data: dict[str, Any] | None = None
    external_id: str | None = None


class ToolOperationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def claim(self, *, context: ToolContext, tool_name: str) -> OperationClaim:
        operation_id = context.operation_id(tool_name)
        async with self.session_factory() as session:
            existing = await self._get(session, operation_id)
            if existing is not None:
                if existing.status == "failed":
                    existing.status = "executing"
                    existing.error = None
                    await session.commit()
                    return OperationClaim(should_execute=True, status="executing")
                return OperationClaim(
                    should_execute=False,
                    status=existing.status,
                    result_data=existing.result_data,
                    external_id=existing.external_id,
                )
            session.add(
                ToolOperation(
                    operation_id=operation_id,
                    tool_name=tool_name,
                    conversation_id=context.conversation_id,
                    source_message_id=context.source_message_id,
                    user_id=context.user_id,
                    status="executing",
                )
            )
            try:
                await session.commit()
                return OperationClaim(should_execute=True, status="executing")
            except IntegrityError:
                await session.rollback()
                existing = await self._get(session, operation_id)
                if existing is None:
                    raise
                return OperationClaim(
                    should_execute=False,
                    status=existing.status,
                    result_data=existing.result_data,
                    external_id=existing.external_id,
                )

    async def succeed(
        self,
        *,
        context: ToolContext,
        tool_name: str,
        external_id: str,
        result_data: dict[str, Any],
    ) -> None:
        async with self.session_factory() as session:
            operation = await self._get(session, context.operation_id(tool_name))
            if operation is None:
                raise RuntimeError("tool operation was not claimed")
            operation.status = "succeeded"
            operation.external_id = external_id
            operation.result_data = result_data
            operation.error = None
            await session.commit()

    async def fail(
        self, *, context: ToolContext, tool_name: str, error: str
    ) -> None:
        async with self.session_factory() as session:
            operation = await self._get(session, context.operation_id(tool_name))
            if operation is not None:
                operation.status = "failed"
                operation.error = error
                await session.commit()

    @staticmethod
    async def _get(session: AsyncSession, operation_id: str) -> ToolOperation | None:
        return await session.scalar(
            select(ToolOperation).where(ToolOperation.operation_id == operation_id)
        )
