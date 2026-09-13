import json
import re

from pydantic import BaseModel, Field, field_validator

from app.schemas.message import OutboundFile
from app.services.document_service import DocumentService
from app.tools.base import StrictToolArgs, Tool, ToolResponse
from app.tools.context import ToolContext


class DocumentMetadata(StrictToolArgs):
    label: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=1000)


class DocumentSection(StrictToolArgs):
    heading: str = Field(min_length=1, max_length=200)
    paragraphs: list[str] = Field(default_factory=list, max_length=30)
    bullets: list[str] = Field(default_factory=list, max_length=50)
    numbered_items: list[str] = Field(default_factory=list, max_length=50)
    table: list[list[str]] = Field(default_factory=list, max_length=50)


class GenerateDocumentArgs(StrictToolArgs):
    title: str = Field(min_length=1, max_length=200)
    filename: str | None = Field(default=None, max_length=180)
    subtitle: str | None = Field(default=None, max_length=500)
    summary: str | None = Field(default=None, max_length=5000)
    metadata: list[DocumentMetadata] = Field(default_factory=list, max_length=30)
    sections: list[DocumentSection] = Field(min_length=1, max_length=30)

    @field_validator("filename")
    @classmethod
    def normalize_filename(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value).strip(" .")
        if not cleaned:
            return None
        return cleaned if cleaned.lower().endswith(".docx") else f"{cleaned}.docx"


class GenerateDocumentTool(Tool):
    name = "generate_document"
    description = (
        "Generate and attach a real Microsoft Word .docx file. You MUST call this tool "
        "when the user asks to generate, export, download, or send a document/file. "
        "First obtain any required facts with other tools. Put facts in metadata, prose in "
        "paragraphs, lists in bullets/numbered_items, and rectangular tabular data in table."
    )
    permission = "read"
    args_model = GenerateDocumentArgs

    def __init__(self, service: DocumentService) -> None:
        self.service = service

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = GenerateDocumentArgs.model_validate(args)
        filename = values.filename or self._filename_from_title(values.title)
        data = self.service.generate(
            title=values.title,
            subtitle=values.subtitle,
            summary=values.summary,
            metadata=[item.model_dump() for item in values.metadata],
            sections=[item.model_dump() for item in values.sections],
        )
        result = {
            "filename": filename,
            "content_type": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            "size_bytes": len(data),
            "status": "generated",
        }
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=json.dumps(result, ensure_ascii=False),
            display_data=result,
            files=[
                OutboundFile(
                    name=filename,
                    content_type=result["content_type"],
                    data=data,
                )
            ],
        )

    @staticmethod
    def _filename_from_title(title: str) -> str:
        cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", title).strip(" .")
        return f"{(cleaned or 'FlowAgent文档')[:160]}.docx"
