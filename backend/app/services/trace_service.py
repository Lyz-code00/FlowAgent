from datetime import datetime, timezone
from time import monotonic
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AgentRun, AgentStep


class TraceService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self._started: dict[int, float] = {}

    async def start(
        self, *, conversation_id: int, source_message_id: int, model: str
    ) -> int:
        async with self.session_factory() as session:
            run = AgentRun(
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                model=model,
                status="running",
            )
            session.add(run)
            await session.commit()
            self._started[run.id] = monotonic()
            return run.id

    async def record_step(
        self,
        *,
        run_id: int,
        step_no: int,
        kind: str,
        status: str,
        name: str | None = None,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        latency_ms: int | None = None,
        error: str | None = None,
    ) -> None:
        async with self.session_factory() as session:
            session.add(
                AgentStep(
                    run_id=run_id,
                    step_no=step_no,
                    kind=kind,
                    status=status,
                    name=name,
                    input_data=input_data,
                    output_data=output_data,
                    latency_ms=latency_ms,
                    error=error,
                )
            )
            await session.commit()

    async def finish(
        self,
        run_id: int,
        *,
        final_answer: str | None = None,
        error: str | None = None,
        completion_status: str | None = None,
    ) -> None:
        async with self.session_factory() as session:
            run = await session.get(AgentRun, run_id)
            if run is None:
                return
            started = self._started.pop(run_id, None)
            run.status = "failed" if error else (completion_status or "succeeded")
            run.final_answer = final_answer
            run.error = error
            run.completed_at = datetime.now(timezone.utc)
            if started is not None:
                run.latency_ms = int((monotonic() - started) * 1000)
            await session.commit()
