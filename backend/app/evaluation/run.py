from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select

from app.db.models import InboundEventAudit
from app.db.session import create_engine, create_session_factory, create_tables
from app.rag.embedding import DevelopmentHashEmbeddingProvider, cosine_similarity
from app.schemas.message import UnifiedMessage
from app.services.confirmation_service import ConfirmationService
from app.services.conversation_service import ConversationService
from app.services.identity_service import IdentityService
from app.services.knowledge_service import KnowledgeService
from app.tools.context import ToolContext


CORPUS = [
    "支付回调：PaymentSucceededEvent 成功后由 order-consumer 更新订单状态；异常时检查 MQ lag。",
    "登录鉴权：401 TOKEN_EXPIRED 表示访问令牌过期，应刷新 token 后重试。",
    "发布流程：生产发布必须通过灰度、健康检查和回滚检查点。",
    "GitHub Issue：P1 高风险建单必须取得确认码并由用户二次确认。",
    "飞书事件：im.message.receive_v1 可能重复投递，按 message_id 做幂等去重。",
    "知识库：支持 Markdown、TXT、文本型 PDF，检索答案必须保留 Citation。",
    "监控排障：服务健康查 health，指标查 Prometheus，日志查 Loki，错误查 Sentry。",
    "负责人映射：通过服务名查找团队、飞书 open_id 和 GitHub username。",
    "会话记忆：默认保留最近十轮，并从历史摘要、URL、Issue 编号提取长期锚点。",
    "文档生成：generate_document 生成 DOCX，并通过飞书消息发送真实文件。",
]

CASES = [
    ("支付成功但订单仍然 pending 要检查什么", 0),
    ("PaymentSucceededEvent 是谁消费的", 0),
    ("TOKEN_EXPIRED 如何处理", 1),
    ("登录接口返回 401 怎么办", 1),
    ("生产上线之前有哪些检查", 2),
    ("发布失败如何预留回滚点", 2),
    ("创建 P1 为什么需要确认码", 3),
    ("高风险 Issue 的二次确认规则", 3),
    ("飞书消息为什么会收到两次", 4),
    ("im.message.receive_v1 幂等键是什么", 4),
    ("知识库可以上传哪些格式", 5),
    ("RAG 回答如何标注来源", 5),
    ("查询线上错误应该用哪个系统", 6),
    ("Prometheus Loki Sentry 分别查什么", 6),
    ("如何查后端服务负责人 GitHub 账号", 7),
    ("owner lookup 能返回哪些身份字段", 7),
    ("超过十轮后 Issue 编号还能记住吗", 8),
    ("长期记忆会保留哪些锚点", 8),
    ("能不能生成 Word 文档", 9),
    ("生成的 DOCX 如何发到飞书", 9),
]


def _offline_context_cases() -> list[dict]:
    details: list[dict] = []
    for index in range(10):
        issue_no = 201 + index
        url = f"https://github.com/Lyz-code00/FlowAgent/issues/{issue_no}"
        memory = ConversationService._build_long_term_memory(
            None,
            [SimpleNamespace(role="user", content=f"请记住 Issue #{issue_no}，链接 {url}")],
        )
        details.append(
            {
                "scenario": f"历史 Issue 与 URL #{issue_no}",
                "passed": f"#{issue_no}" in memory and url in memory,
            }
        )
    for index in range(10):
        requirement = f"必须在部署 service-{index} 前完成回滚检查"
        memory = ConversationService._build_long_term_memory(
            None,
            [SimpleNamespace(role="user", content=requirement)],
        )
        details.append(
            {"scenario": f"历史约束 service-{index}", "passed": requirement in memory}
        )
    for index in range(10):
        action = f"验收 module-{index} 的飞书闭环"
        summary = SimpleNamespace(
            status="confirmed",
            summary=f"module-{index} 项目讨论",
            decisions=["真实写操作必须调用工具"],
            bugs=[],
            action_items=[{"content": action, "status": "pending"}],
        )
        memory = ConversationService._build_long_term_memory(summary, [])
        details.append(
            {"scenario": f"已确认摘要待办 module-{index}", "passed": action in memory}
        )
    return details


async def _offline_operation_cases() -> dict:
    with tempfile.TemporaryDirectory(prefix="flowagent-eval-") as directory:
        engine = create_engine(f"sqlite+aiosqlite:///{Path(directory) / 'eval.db'}")
        await create_tables(engine)
        factory = create_session_factory(engine)
        conversations = ConversationService(factory, IdentityService())
        message = UnifiedMessage(
            platform="feishu",
            tenant_id="offline-eval",
            external_user_id="offline-user",
            conversation_id="offline-conversation",
            message_id="offline-duplicate-event",
            message_type="text",
            text="重复事件验收",
        )
        try:
            accepted = await conversations.accept_inbound(message)
            duplicate_results = [
                await conversations.accept_inbound(message) for _ in range(99)
            ]
            async with factory() as session:
                audit_total = int(
                    await session.scalar(select(func.count(InboundEventAudit.id))) or 0
                )
                duplicate_total = int(
                    await session.scalar(
                        select(func.count(InboundEventAudit.id)).where(
                            InboundEventAudit.duplicate.is_(True)
                        )
                    )
                    or 0
                )

            confirmation_passed = 0
            if accepted is not None:
                confirmations = ConfirmationService(factory)
                context = ToolContext(
                    tenant_id=accepted.tenant_id,
                    user_id=accepted.user_id,
                    user_role=accepted.role,
                    conversation_id=accepted.conversation_id,
                    source_message_id=accepted.message_id,
                    external_message_id=message.message_id,
                )
                for index in range(30):
                    arguments = {
                        "title": f"P1 confirmation case {index}",
                        "body": "offline benchmark",
                        "labels": ["bug", "P1"],
                    }
                    code = await confirmations.issue(
                        context=context,
                        tool_name="github_create_issue",
                        arguments=arguments,
                    )
                    consumed, _ = await confirmations.consume(
                        context=context,
                        tool_name="github_create_issue",
                        arguments=arguments,
                        code=code,
                    )
                    reused, _ = await confirmations.consume(
                        context=context,
                        tool_name="github_create_issue",
                        arguments=arguments,
                        code=code,
                    )
                    confirmation_passed += int(consumed and not reused)
            return {
                "dedup_passed": int(
                    accepted is not None
                    and all(result is None for result in duplicate_results)
                    and audit_total == 100
                    and duplicate_total == 99
                ),
                "dedup_total": 1,
                "deliveries": audit_total,
                "duplicates": duplicate_total,
                "confirmation_passed": confirmation_passed,
                "confirmation_total": 30,
            }
        finally:
            await engine.dispose()


async def run() -> dict:
    provider = DevelopmentHashEmbeddingProvider(dimensions=256)
    corpus_vectors = await provider.embed(CORPUS)
    passed = 0
    details = []
    for query, expected in CASES:
        query_vector = (await provider.embed([query]))[0]
        lexical = KnowledgeService._bm25_scores(query, CORPUS)
        max_lexical = max(lexical, default=0) or 1
        scored = []
        for index, vector in enumerate(corpus_vectors):
            dense = cosine_similarity(query_vector, vector)
            score = 0.65 * max(0, min(1, (dense + 1) / 2)) + 0.35 * lexical[index] / max_lexical
            scored.append((score, index))
        top_k = [index for _, index in sorted(scored, reverse=True)[:5]]
        ok = expected in top_k
        passed += int(ok)
        details.append({"query": query, "expected_document": expected + 1, "top_k": [item + 1 for item in top_k], "passed": ok})

    context_cases = _offline_context_cases()
    context_passed = sum(item["passed"] for item in context_cases)
    operation_cases = await _offline_operation_cases()

    return {
        "suite": "flowagent-builtin-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": [
            {
                "key": "rag_recall_at_5",
                "label": "RAG Recall@5",
                "value": round(passed / len(CASES) * 100, 2),
                "unit": "%",
                "numerator": passed,
                "denominator": len(CASES),
                "status": "measured",
                "source": "offline_builtin",
                "note": "20 条内置研发知识问答，混合检索命中预期文档",
            },
            {
                "key": "context_evidence_retention",
                "label": "多轮上下文证据保留率",
                "value": round(context_passed / len(context_cases) * 100, 2),
                "unit": "%",
                "numerator": context_passed,
                "denominator": len(context_cases),
                "status": "measured",
                "source": "offline_builtin",
                "note": "30 组历史 Issue/URL、明确约束和已确认摘要待办保留测试；不等同于线上模型语义成功率",
            },
            {
                "key": "event_dedup_offline",
                "label": "重复事件去重验收",
                "value": 100.0 if operation_cases["dedup_passed"] else 0.0,
                "unit": "%",
                "numerator": operation_cases["duplicates"],
                "denominator": 99,
                "status": "measured",
                "source": "offline_builtin",
                "note": "同一飞书 message_id 连续投递 100 次，仅首条进入处理，99 次重复均被拦截",
            },
            {
                "key": "confirmation_single_use",
                "label": "高风险确认单次消费通过率",
                "value": round(
                    operation_cases["confirmation_passed"]
                    / operation_cases["confirmation_total"]
                    * 100,
                    2,
                ),
                "unit": "%",
                "numerator": operation_cases["confirmation_passed"],
                "denominator": operation_cases["confirmation_total"],
                "status": "measured",
                "source": "offline_builtin",
                "note": "30 组确认码均只允许绑定操作首次消费，复用全部拒绝",
            },
        ],
        "rag_cases": details,
        "context_cases": context_cases,
        "operation_cases": operation_cases,
    }


async def main() -> None:
    result = await run()
    output = Path(__file__).with_name("latest.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
