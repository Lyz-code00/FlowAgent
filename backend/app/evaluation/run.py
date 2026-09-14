from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.rag.embedding import DevelopmentHashEmbeddingProvider, cosine_similarity
from app.services.conversation_service import ConversationService
from app.services.knowledge_service import KnowledgeService


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

    context_passed = 0
    for issue_no in range(101, 121):
        url = f"https://github.com/Lyz-code00/FlowAgent/issues/{issue_no}"
        older_rows = [
            SimpleNamespace(
                role="user", content=f"请记住 Issue #{issue_no}，链接 {url}"
            )
        ]
        memory = ConversationService._build_long_term_memory(None, older_rows)
        context_passed += int(f"#{issue_no}" in memory and url in memory)

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
                "key": "long_term_anchor_recall",
                "label": "长期记忆锚点召回率",
                "value": round(context_passed / 20 * 100, 2),
                "unit": "%",
                "numerator": context_passed,
                "denominator": 20,
                "status": "measured",
                "source": "offline_builtin",
                "note": "20 条超过近期窗口的 Issue 编号与 URL 保留测试；不等同于线上模型语义成功率",
            },
        ],
        "rag_cases": details,
    }


async def main() -> None:
    result = await run()
    output = Path(__file__).with_name("latest.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
