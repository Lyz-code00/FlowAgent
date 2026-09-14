from dataclasses import asdict, dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import OwnershipMapping, Tenant


@dataclass(frozen=True)
class OwnershipInfo:
    id: int
    tenant_id: int
    tenant_key: str
    service: str
    team: str
    display_name: str
    feishu_open_id: str
    github_username: str
    active: bool


class OwnershipService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def search(
        self, *, tenant_id: int, query: str | None = None, limit: int = 20
    ) -> list[OwnershipInfo]:
        statement = (
            select(OwnershipMapping, Tenant.external_key)
            .join(Tenant, Tenant.id == OwnershipMapping.tenant_id)
            .where(
                OwnershipMapping.tenant_id == tenant_id,
                OwnershipMapping.active.is_(True),
            )
        )
        if query and query.strip():
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    OwnershipMapping.service.ilike(pattern),
                    OwnershipMapping.team.ilike(pattern),
                    OwnershipMapping.display_name.ilike(pattern),
                    OwnershipMapping.github_username.ilike(pattern),
                )
            )
        async with self.session_factory() as session:
            rows = (
                await session.execute(statement.order_by(OwnershipMapping.service).limit(limit))
            ).all()
        return [self._info(mapping, tenant_key) for mapping, tenant_key in rows]

    async def list_all(
        self, *, tenant_key: str | None = None
    ) -> list[dict]:
        statement = select(OwnershipMapping, Tenant.external_key).join(
            Tenant, Tenant.id == OwnershipMapping.tenant_id
        )
        if tenant_key:
            statement = statement.where(Tenant.external_key == tenant_key)
        async with self.session_factory() as session:
            rows = (
                await session.execute(statement.order_by(Tenant.id, OwnershipMapping.service))
            ).all()
        return [asdict(self._info(mapping, key)) for mapping, key in rows]

    async def create(
        self,
        *,
        tenant_id: int,
        service: str,
        team: str = "",
        display_name: str = "",
        feishu_open_id: str = "",
        github_username: str = "",
        active: bool = True,
    ) -> dict:
        async with self.session_factory() as session:
            tenant_key = await session.scalar(
                select(Tenant.external_key).where(Tenant.id == tenant_id)
            )
            if tenant_key is None:
                raise ValueError("tenant not found")
            mapping = OwnershipMapping(
                tenant_id=tenant_id,
                service=service.strip(),
                team=team.strip(),
                display_name=display_name.strip(),
                feishu_open_id=feishu_open_id.strip(),
                github_username=github_username.strip(),
                active=active,
            )
            session.add(mapping)
            await session.commit()
            await session.refresh(mapping)
            return asdict(self._info(mapping, tenant_key))

    async def update(self, mapping_id: int, **values) -> dict | None:
        async with self.session_factory() as session:
            mapping = await session.get(OwnershipMapping, mapping_id)
            if mapping is None:
                return None
            for field in (
                "service",
                "team",
                "display_name",
                "feishu_open_id",
                "github_username",
            ):
                if field in values:
                    setattr(mapping, field, str(values[field]).strip())
            if "active" in values:
                mapping.active = bool(values["active"])
            tenant_key = await session.scalar(
                select(Tenant.external_key).where(Tenant.id == mapping.tenant_id)
            )
            await session.commit()
            await session.refresh(mapping)
            return asdict(self._info(mapping, tenant_key or ""))

    async def delete(self, mapping_id: int) -> bool:
        async with self.session_factory() as session:
            mapping = await session.get(OwnershipMapping, mapping_id)
            if mapping is None:
                return False
            await session.delete(mapping)
            await session.commit()
            return True

    @staticmethod
    def _info(mapping: OwnershipMapping, tenant_key: str) -> OwnershipInfo:
        return OwnershipInfo(
            id=mapping.id,
            tenant_id=mapping.tenant_id,
            tenant_key=tenant_key,
            service=mapping.service,
            team=mapping.team,
            display_name=mapping.display_name,
            feishu_open_id=mapping.feishu_open_id,
            github_username=mapping.github_username,
            active=mapping.active,
        )
