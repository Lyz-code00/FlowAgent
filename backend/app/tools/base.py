from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.tools.context import ToolContext


class StrictToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyArgs(StrictToolArgs):
    pass


class ToolResponse(BaseModel):
    tool_name: str
    success: bool
    llm_content: str
    display_data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    latency_ms: int = 0


class Tool(ABC):
    name: str
    description: str
    permission: str = "read"
    args_model: type[BaseModel] = EmptyArgs

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.args_model.model_json_schema(),
        }

    @abstractmethod
    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        pass
