import json
from dataclasses import asdict

from pydantic import BaseModel, Field, HttpUrl

from app.services.feishu_document_service import FeishuDocumentService
from app.tools.base import StrictToolArgs, Tool, ToolResponse
from app.tools.context import ToolContext


class FeishuImportDocumentArgs(StrictToolArgs):
    url: HttpUrl
    title: str | None = Field(default=None, max_length=512)


class FeishuImportDocumentTool(Tool):
    name = "feishu_import_document"
    description = (
        "Import or refresh a Feishu docx/Wiki document into the current tenant's "
        "internal knowledge base. Use only when the user explicitly asks to import "
        "or sync a Feishu document link."
    )
    permission = "knowledge_write"
    args_model = FeishuImportDocumentArgs

    def __init__(self, service: FeishuDocumentService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = FeishuImportDocumentArgs.model_validate(args)
        imported = await self.service.import_url(
            tenant_id=context.tenant_id,
            url=str(values.url),
            title=values.title,
        )
        data = {
            "document": asdict(imported.document),
            "source_url": imported.source_url,
            "document_token": imported.document_token,
            "replaced_versions": imported.replaced_versions,
        }
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(data, ensure_ascii=False),
            display_data=data,
        )
