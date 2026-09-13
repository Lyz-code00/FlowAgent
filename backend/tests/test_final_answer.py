import pytest
from pydantic import ValidationError

from app.tools.final_answer import SubmitFinalAnswerArgs


def test_submit_final_answer_preserves_markdown_and_links() -> None:
    answer = (
        "## 结果\n\n"
        "- **Issue #3**：https://github.com/Lyz-code00/FlowAgent/issues/3\n"
        "- 配置项：`FLOWAGENT_LLM_MODEL` [1]"
    )
    args = SubmitFinalAnswerArgs.model_validate(
        {"answer": answer, "status": "resolved", "citations": [1]}
    )
    assert args.answer == answer
    assert args.citations == [1]


def test_partial_answer_requires_unresolved_items_and_next_step() -> None:
    with pytest.raises(ValidationError):
        SubmitFinalAnswerArgs.model_validate(
            {"answer": "还没处理完", "status": "partial"}
        )

    args = SubmitFinalAnswerArgs.model_validate(
        {
            "answer": "图片已支持，语音尚未配置转写服务。",
            "status": "partial",
            "unresolved_items": ["配置语音转写服务"],
            "next_step": "提供兼容的语音转写 API 配置。",
        }
    )
    assert args.status == "partial"


def test_resolved_answer_rejects_unresolved_items() -> None:
    with pytest.raises(ValidationError):
        SubmitFinalAnswerArgs.model_validate(
            {
                "answer": "完成",
                "status": "resolved",
                "unresolved_items": ["其实没完成"],
            }
        )


def test_submit_final_answer_args_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SubmitFinalAnswerArgs.model_validate({"answer": "ok", "issue_number": 1})
