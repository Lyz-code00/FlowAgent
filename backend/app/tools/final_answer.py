from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.tools.base import StrictToolArgs, Tool, ToolResponse
from app.tools.context import ToolContext


class SubmitFinalAnswerArgs(StrictToolArgs):
    """约束事实和完成状态，但不破坏模型生成的正文格式。"""

    answer: str = Field(
        min_length=1,
        max_length=12000,
        description=(
            "给用户的最终正文。使用清晰纯文本和中文编号，不使用 Markdown 装饰符。"
            "不得删除或改写工具返回的 URL；用户索要链接时必须给出工具验证过的完整 URL。"
            "引用知识库证据时保留 [数字] 标记。"
        ),
    )
    status: Literal["resolved", "partial", "blocked"] = Field(
        default="resolved",
        description=(
            "resolved=用户实际问题已经解决；partial=只完成一部分；"
            "blocked=缺少权限、信息或外部条件。不能仅因要结束本轮就填写 resolved。"
        ),
    )
    unresolved_items: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="仍未完成的事项；resolved 时应为空。",
    )
    next_step: str | None = Field(
        default=None,
        max_length=1000,
        description="partial/blocked 时给用户的一个明确下一步；无后续则留空。",
    )
    citations: list[int] = Field(
        default_factory=list,
        description="本次回答引用的知识库 citation_id 列表，没有引用则留空。",
    )

    @model_validator(mode="after")
    def validate_completion_state(self) -> "SubmitFinalAnswerArgs":
        if self.status == "resolved" and self.unresolved_items:
            raise ValueError("resolved responses cannot contain unresolved_items")
        if self.status in {"partial", "blocked"}:
            if not self.unresolved_items:
                raise ValueError("partial/blocked responses require unresolved_items")
            if not self.next_step:
                raise ValueError("partial/blocked responses require next_step")
        return self

class SubmitFinalAnswerTool(Tool):
    name = "submit_final_answer"
    description = (
        "结束本轮并提交最终回复。它是事实与完成状态协议，不是文本清洗器："
        "格式由生成规章约束而不做字符过滤，完整 URL 必须保留。必须如实填写 status；只要用户的实际问题仍未解决，"
        "就使用 partial 或 blocked，并填写 unresolved_items 与 next_step。"
        "凡 GitHub 工具返回 html_url 且用户索要链接，answer 必须原样包含该 URL。"
    )
    args_model = SubmitFinalAnswerArgs

    async def run(self, context: ToolContext, args: BaseModel) -> ToolResponse:
        values = SubmitFinalAnswerArgs.model_validate(args)
        return ToolResponse(
            tool_name=self.name,
            success=True,
            llm_content=values.answer,
            display_data=values.model_dump(),
        )
