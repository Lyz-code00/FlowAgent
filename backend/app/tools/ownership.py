import json
from dataclasses import asdict

from pydantic import BaseModel, Field

from app.services.ownership_service import OwnershipService
from app.tools.base import StrictToolArgs, Tool, ToolResponse
from app.tools.context import ToolContext


class OwnerLookupArgs(StrictToolArgs):
    query: str = Field(min_length=1, max_length=255)
    limit: int = Field(default=10, ge=1, le=20)


class OwnerLookupTool(Tool):
    name = "owner_lookup"
    description = (
        "Resolve a service, module, team, or human role to configured owner details and "
        "a GitHub username. Use before assigning an issue when the user names a role "
        "rather than an exact GitHub username."
    )
    args_model = OwnerLookupArgs

    def __init__(self, service: OwnershipService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = OwnerLookupArgs.model_validate(args)
        owners = await self.service.search(
            tenant_id=context.tenant_id, query=values.query, limit=values.limit
        )
        data = [asdict(item) for item in owners]
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=(
                json.dumps(data, ensure_ascii=False)
                + "\n只能使用返回的 github_username 指派 Issue；空值或多条歧义时须询问用户。"
            ),
            display_data={"owners": data},
        )
