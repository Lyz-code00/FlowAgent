from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Incident


@dataclass(frozen=True)
class IncidentInfo:
    id: int
    incident_key: str
    title: str
    status: str
    severity: str
    service: str | None
    error_code: str | None
    occurred_at: str | None
    summary: str
    root_cause: str | None
    evidence: list[str]
    source_url: str | None
    created_by_user_id: int
    created_at: str
    updated_at: str


class IncidentService:
    VALID_STATUSES = {"open", "investigating", "mitigated", "resolved"}
    VALID_SEVERITIES = {"P0", "P1", "P2", "P3", "P4", "unknown"}

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def create(
        self,
        *,
        tenant_id: int,
        created_by_user_id: int,
        title: str,
        summary: str,
        status: str = "open",
        severity: str = "unknown",
        service: str | None = None,
        error_code: str | None = None,
        occurred_at: str | None = None,
        root_cause: str | None = None,
        evidence: list[str] | None = None,
        source_url: str | None = None,
    ) -> IncidentInfo:
        self._validate(status=status, severity=severity)
        async with self.session_factory() as session:
            incident = Incident(
                tenant_id=tenant_id,
                incident_key=f"pending-{uuid4().hex[:20]}",
                title=title.strip(),
                status=status,
                severity=severity,
                service=self._clean(service),
                error_code=self._clean(error_code),
                occurred_at=self._clean(occurred_at),
                summary=summary.strip(),
                root_cause=self._clean(root_cause),
                evidence=[item.strip() for item in (evidence or []) if item.strip()],
                source_url=self._clean(source_url),
                created_by_user_id=created_by_user_id,
            )
            session.add(incident)
            await session.flush()
            incident.incident_key = f"INC-{incident.id:04d}"
            await session.commit()
            await session.refresh(incident)
            return self._info(incident)

    async def search(
        self,
        *,
        tenant_id: int,
        query: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        service: str | None = None,
        limit: int = 10,
    ) -> list[IncidentInfo]:
        if status is not None or severity is not None:
            self._validate(
                status=status or "open", severity=severity or "unknown"
            )
        statement = select(Incident).where(Incident.tenant_id == tenant_id)
        if query and query.strip():
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    Incident.incident_key.ilike(pattern),
                    Incident.title.ilike(pattern),
                    Incident.summary.ilike(pattern),
                    Incident.root_cause.ilike(pattern),
                    Incident.service.ilike(pattern),
                    Incident.error_code.ilike(pattern),
                )
            )
        if status:
            statement = statement.where(Incident.status == status)
        if severity:
            statement = statement.where(Incident.severity == severity)
        if service:
            statement = statement.where(Incident.service == service.strip())
        async with self.session_factory() as session:
            incidents = (
                await session.scalars(
                    statement.order_by(Incident.id.desc()).limit(limit)
                )
            ).all()
        return [self._info(item) for item in incidents]

    async def list_all(self, *, limit: int = 100) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            incidents = (
                await session.scalars(
                    select(Incident).order_by(Incident.id.desc()).limit(limit)
                )
            ).all()
        return [asdict(self._info(item)) for item in incidents]

    @classmethod
    def _validate(cls, *, status: str, severity: str) -> None:
        if status not in cls.VALID_STATUSES:
            raise ValueError(f"invalid incident status: {status}")
        if severity not in cls.VALID_SEVERITIES:
            raise ValueError(f"invalid incident severity: {severity}")

    @staticmethod
    def _clean(value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None

    @staticmethod
    def _info(incident: Incident) -> IncidentInfo:
        return IncidentInfo(
            id=incident.id,
            incident_key=incident.incident_key,
            title=incident.title,
            status=incident.status,
            severity=incident.severity,
            service=incident.service,
            error_code=incident.error_code,
            occurred_at=incident.occurred_at,
            summary=incident.summary,
            root_cause=incident.root_cause,
            evidence=list(incident.evidence or []),
            source_url=incident.source_url,
            created_by_user_id=incident.created_by_user_id,
            created_at=incident.created_at.isoformat(),
            updated_at=incident.updated_at.isoformat(),
        )
