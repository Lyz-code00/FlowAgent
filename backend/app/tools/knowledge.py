import json

from pydantic import BaseModel, Field

from app.services.knowledge_service import KnowledgeService
from app.tools.base import StrictToolArgs, Tool, ToolResponse
from app.tools.context import ToolContext


class KnowledgeSearchArgs(StrictToolArgs):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int | None = Field(default=None, ge=1, le=10)


class KnowledgeSearchTool(Tool):
    name = "knowledge_search"
    description = (
        "Search the current tenant's internal knowledge base and return cited evidence."
    )
    args_model = KnowledgeSearchArgs
    retryable = True

    def __init__(self, service: KnowledgeService, *, default_top_k: int = 5) -> None:
        self.service = service
        self.default_top_k = default_top_k

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = KnowledgeSearchArgs.model_validate(args)
        hits = await self.service.search(
            tenant_id=context.tenant_id,
            query=values.query,
            top_k=values.top_k or self.default_top_k,
        )
        data = [
            {
                "citation_id": hit.citation_id,
                "title": hit.title,
                "source": hit.source_name,
                "locator": hit.source_locator,
                "content": hit.content,
                "score": hit.score,
                "dense_score": hit.dense_score,
                "lexical_score": hit.lexical_score,
            }
            for hit in hits
        ]
        if not data:
            return ToolResponse(
                tool_name=self.name,
                success=True,
                llm_content=(
                    "内部知识库未找到足够依据。不要编造 Citation；请明确告知用户无可靠召回。"
                ),
                display_data={"results": []},
            )
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=(
                json.dumps(data, ensure_ascii=False)
                + "\n回答时必须使用对应的 [citation_id] 标记引用。"
            ),
            display_data={"results": data},
        )
