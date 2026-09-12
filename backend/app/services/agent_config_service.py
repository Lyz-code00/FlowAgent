from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AgentConfig


@dataclass(frozen=True)
class AgentRuntimeConfig:
    name: str
    model: str
    system_prompt: str
    max_steps: int
    knowledge_enabled: bool
    github_enabled: bool


class AgentConfigService:
    CONFIG_ID = 1

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def ensure_default(
        self, *, model: str, system_prompt: str, max_steps: int
    ) -> AgentRuntimeConfig:
        async with self.session_factory() as session:
            row = await session.get(AgentConfig, self.CONFIG_ID)
            if row is None:
                row = AgentConfig(
                    id=self.CONFIG_ID,
                    name="FlowAgent",
                    model=model,
                    system_prompt=system_prompt,
                    max_steps=max_steps,
                    knowledge_enabled=True,
                    github_enabled=True,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
            return self._serialize(row)

    async def get(self) -> AgentRuntimeConfig:
        async with self.session_factory() as session:
            row = await session.get(AgentConfig, self.CONFIG_ID)
            if row is None:
                raise RuntimeError("agent configuration is not initialized")
            return self._serialize(row)

    async def update(
        self,
        *,
        name: str,
        model: str,
        system_prompt: str,
        max_steps: int,
        knowledge_enabled: bool,
        github_enabled: bool,
    ) -> AgentRuntimeConfig:
        async with self.session_factory() as session:
            row = await session.get(AgentConfig, self.CONFIG_ID)
            if row is None:
                raise RuntimeError("agent configuration is not initialized")
            row.name = name
            row.model = model
            row.system_prompt = system_prompt
            row.max_steps = max_steps
            row.knowledge_enabled = knowledge_enabled
            row.github_enabled = github_enabled
            await session.commit()
            await session.refresh(row)
            return self._serialize(row)

    @staticmethod
    def _serialize(row: AgentConfig) -> AgentRuntimeConfig:
        return AgentRuntimeConfig(
            name=row.name,
            model=row.model,
            system_prompt=row.system_prompt,
            max_steps=row.max_steps,
            knowledge_enabled=row.knowledge_enabled,
            github_enabled=row.github_enabled,
        )
