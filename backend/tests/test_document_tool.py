from io import BytesIO

from docx import Document

from app.services.document_service import DocumentService
from app.tools.context import ToolContext
from app.tools.document import GenerateDocumentArgs, GenerateDocumentTool


async def test_generate_document_tool_returns_real_docx_attachment() -> None:
    tool = GenerateDocumentTool(DocumentService())
    response = await tool.run(
        ToolContext(
            tenant_id=1,
            user_id=1,
            user_role="member",
            conversation_id=1,
            source_message_id=1,
            external_message_id="om-1",
        ),
        GenerateDocumentArgs(
            title="FlowAgent 高风险操作确认测试",
            filename="Issue-3报告",
            subtitle="GitHub Issue #3",
            summary="验证 P1 Issue 创建前必须经过二次确认。",
            metadata=[
                {"label": "状态", "value": "open"},
                {"label": "标签", "value": "bug、P1"},
            ],
            sections=[
                {
                    "heading": "要点归纳",
                    "numbered_items": [
                        "验证高风险操作确认流程",
                        "补充复现步骤与验收标准",
                    ],
                }
            ],
        ),
    )

    assert response.success is True
    assert response.display_data["filename"] == "Issue-3报告.docx"
    assert len(response.files) == 1
    assert response.files[0].data.startswith(b"PK")
    generated = Document(BytesIO(response.files[0].data))
    text = "\n".join(paragraph.text for paragraph in generated.paragraphs)
    assert "FlowAgent 高风险操作确认测试" in text
    assert "验证 P1 Issue 创建前必须经过二次确认" in text
    assert "要点归纳" in text


def test_generate_document_filename_is_sanitized() -> None:
    values = GenerateDocumentArgs(
        title="报告",
        filename='Issue/3:*?"',
        sections=[{"heading": "结论", "paragraphs": ["完成"]}],
    )
    assert values.filename == "Issue_3____.docx"
