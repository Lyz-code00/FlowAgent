from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChannelAccount, Tenant, User
from app.schemas.message import UnifiedMessage


@dataclass(frozen=True)
class Identity:
    tenant_id: int
    user_id: int
    role: str


class IdentityService:
    async def resolve(self, session: AsyncSession, message: UnifiedMessage) -> Identity:
        account = await session.scalar(
            select(ChannelAccount).where(
                ChannelAccount.platform == message.platform,
                ChannelAccount.external_user_id == message.external_user_id,
            )
        )
        if account is not None:
            user = await session.get(User, account.user_id)
            if user is None:
                raise RuntimeError("channel account points to a missing user")
            return Identity(tenant_id=user.tenant_id, user_id=user.id, role=user.role)

        tenant = await session.scalar(
            select(Tenant).where(Tenant.external_key == message.tenant_id)
        )
        if tenant is None:
            tenant = Tenant(
                external_key=message.tenant_id,
                name=f"Tenant {message.tenant_id}",
            )
            session.add(tenant)
            await session.flush()

        user = User(
            tenant_id=tenant.id,
            name=message.external_user_id,
            role="member",
        )
        session.add(user)
        await session.flush()
        session.add(
            ChannelAccount(
                user_id=user.id,
                platform=message.platform,
                external_user_id=message.external_user_id,
            )
        )
        await session.flush()
        return Identity(tenant_id=tenant.id, user_id=user.id, role=user.role)
