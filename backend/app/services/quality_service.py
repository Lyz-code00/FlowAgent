from __future__ import annotations

import math
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AgentRun,
    AgentStep,
    Feedback,
    InboundEventAudit,
    Message,
    ToolOperation,
)


class QualityService:
    _CITATION_RE = re.compile(r"(?:\[\d+\]|https?://[^\s<>()]+)")
    _CONTEXT_ISSUE_RE = re.compile(
        r"(?:这个|这个问题|上述|刚才|它).{0,12}(?:Issue|Bug|任务|单)", re.IGNORECASE
    )

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float | None:
        if denominator <= 0:
            return None
        return round(numerator / denominator * 100, 2)

    @staticmethod
    def _metric(
        key: str,
        label: str,
        value: float | None,
        unit: str,
        numerator: int | None,
        denominator: int | None,
        note: str,
    ) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "value": value,
            "unit": unit,
            "numerator": numerator,
            "denominator": denominator,
            "status": "measured" if value is not None else "insufficient_data",
            "source": "production",
            "note": note,
        }

    async def metrics(self, *, days: int = 30) -> dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        async with self.session_factory() as session:
            tool_rows = (
                await session.execute(
                    select(AgentStep.status).where(
                        AgentStep.kind == "tool", AgentStep.created_at >= since
                    )
                )
            ).all()
            issue_rows = (
                await session.execute(
                    select(ToolOperation.status).where(
                        ToolOperation.tool_name == "github_create_issue",
                        ToolOperation.created_at >= since,
                    )
                )
            ).all()
            run_rows = (
                await session.execute(
                    select(AgentRun.id, AgentRun.latency_ms, AgentRun.final_answer).where(
                        AgentRun.started_at >= since,
                        AgentRun.status.in_(("succeeded", "partial", "blocked")),
                    )
                )
            ).all()
            step_rows = (
                await session.execute(
                    select(AgentStep.run_id, AgentStep.step_no).where(
                        AgentStep.created_at >= since
                    )
                )
            ).all()
            knowledge_run_ids = set(
                await session.scalars(
                    select(AgentStep.run_id).where(
                        AgentStep.kind == "tool",
                        AgentStep.name == "knowledge_search",
                        AgentStep.status == "succeeded",
                        AgentStep.created_at >= since,
                    )
                )
            )
            feedback_rows = (
                await session.execute(
                    select(Feedback.rating).where(Feedback.created_at >= since)
                )
            ).all()
            audit_rows = (
                await session.execute(
                    select(InboundEventAudit.duplicate).where(
                        InboundEventAudit.created_at >= since
                    )
                )
            ).all()
            context_messages = (
                await session.execute(
                    select(Message.id, Message.content).where(
                        Message.role == "user", Message.created_at >= since
                    )
                )
            ).all()
            successful_issue_source_ids = set(
                await session.scalars(
                    select(ToolOperation.source_message_id).where(
                        ToolOperation.tool_name == "github_create_issue",
                        ToolOperation.status == "succeeded",
                        ToolOperation.created_at >= since,
                    )
                )
            )

        tool_total = len(tool_rows)
        tool_ok = sum(status == "succeeded" for (status,) in tool_rows)
        issue_total = len(issue_rows)
        issue_ok = sum(status == "succeeded" for (status,) in issue_rows)
        latencies = sorted(
            int(latency) for _, latency, _ in run_rows if latency is not None
        )
        average_latency = round(sum(latencies) / len(latencies), 2) if latencies else None
        p95_latency = (
            float(latencies[max(0, math.ceil(len(latencies) * 0.95) - 1)])
            if latencies
            else None
        )
        steps_by_run: dict[int, set[int]] = {}
        for run_id, step_no in step_rows:
            steps_by_run.setdefault(run_id, set()).add(step_no)
        average_steps = (
            round(sum(len(value) for value in steps_by_run.values()) / len(steps_by_run), 2)
            if steps_by_run
            else None
        )
        answers_by_run = {run_id: answer or "" for run_id, _, answer in run_rows}
        cited = sum(
            bool(self._CITATION_RE.search(answers_by_run.get(run_id, "")))
            for run_id in knowledge_run_ids
        )
        positive = sum(rating == "positive" for (rating,) in feedback_rows)
        feedback_total = len(feedback_rows)
        duplicates = sum(bool(duplicate) for (duplicate,) in audit_rows)
        # A duplicate row is written only after the unique message constraint blocked it.
        dedup_success = duplicates
        context_candidates = [
            message_id
            for message_id, content in context_messages
            if self._CONTEXT_ISSUE_RE.search(content)
        ]
        context_success = sum(
            message_id in successful_issue_source_ids for message_id in context_candidates
        )

        return {
            "window_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "metrics": [
                self._metric("tool_success_rate", "Tool Call 成功率", self._ratio(tool_ok, tool_total), "%", tool_ok, tool_total, "成功 Tool Step / 全部 Tool Step"),
                self._metric("issue_success_rate", "GitHub Issue 创建成功率", self._ratio(issue_ok, issue_total), "%", issue_ok, issue_total, "真实创建成功 / 创建尝试"),
                self._metric("citation_coverage", "Citation 覆盖率", self._ratio(cited, len(knowledge_run_ids)), "%", cited, len(knowledge_run_ids), "使用知识库且最终答案带 Citation 或来源 URL"),
                self._metric("average_agent_steps", "平均 Agent Steps", average_steps, "步", sum(len(value) for value in steps_by_run.values()), len(steps_by_run), "按每个 Agent Run 的不同 step_no 统计"),
                self._metric("average_response_ms", "平均响应时间", average_latency, "ms", None, len(latencies), "已完成 Agent Run 的端到端耗时"),
                self._metric("p95_response_ms", "P95 响应时间", p95_latency, "ms", None, len(latencies), "最近窗口内端到端耗时第 95 百分位"),
                self._metric("event_dedup_rate", "重复事件去重率", self._ratio(dedup_success, duplicates), "%", dedup_success, duplicates, "被唯一消息约束成功拦截的重复投递"),
                self._metric("context_issue_success_rate", "多轮上下文成功率", self._ratio(context_success, len(context_candidates)), "%", context_success, len(context_candidates), "含指代表达的建单请求中真实建单成功占比"),
                self._metric("positive_feedback_rate", "用户正向反馈率", self._ratio(positive, feedback_total), "%", positive, feedback_total, "正向反馈 / 全部已评价回答"),
            ],
        }

    @staticmethod
    def benchmark() -> dict[str, Any]:
        path = Path(__file__).parents[1] / "evaluation" / "latest.json"
        if not path.exists():
            return {"suite": "not-run", "generated_at": None, "metrics": []}
        return json.loads(path.read_text())
