from app.db.models import AgentRun, AgentStep, Feedback, Message, ToolOperation
from app.db.session import create_engine, create_session_factory, create_tables
from app.evaluation.run import run as run_benchmark
from app.schemas.message import UnifiedMessage
from app.services.conversation_service import ConversationService
from app.services.identity_service import IdentityService
from app.services.quality_service import QualityService


async def test_quality_metrics_use_real_samples_and_track_duplicates(tmp_path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'quality.db'}")
    await create_tables(engine)
    factory = create_session_factory(engine)
    conversations = ConversationService(factory, IdentityService())
    message = UnifiedMessage(
        platform="feishu",
        tenant_id="tenant-quality",
        external_user_id="ou-quality",
        conversation_id="oc-quality",
        message_id="om-quality",
        message_type="text",
        text="把这个建个 Bug",
    )
    try:
        inbound = await conversations.accept_inbound(message)
        assert inbound is not None
        assert await conversations.accept_inbound(message) is None
        async with factory() as session:
            answer = Message(
                conversation_id=inbound.conversation_id,
                role="assistant",
                content="已依据知识库处理。[1]",
            )
            session.add(answer)
            await session.flush()
            session.add(Feedback(message_id=answer.id, rating="positive"))
            agent_run = AgentRun(
                conversation_id=inbound.conversation_id,
                source_message_id=inbound.message_id,
                model="test-model",
                status="succeeded",
                final_answer="已依据知识库处理。[1]",
                latency_ms=1200,
            )
            session.add(agent_run)
            await session.flush()
            session.add_all(
                [
                    AgentStep(run_id=agent_run.id, step_no=1, kind="tool", status="succeeded", name="knowledge_search", latency_ms=40),
                    AgentStep(run_id=agent_run.id, step_no=2, kind="llm", status="succeeded", name="test-model", latency_ms=200),
                    AgentStep(run_id=agent_run.id, step_no=3, kind="tool", status="failed", name="github_get_file", latency_ms=20, error="invalid tool arguments"),
                ]
            )
            session.add(
                ToolOperation(
                    operation_id="quality-operation",
                    tool_name="github_create_issue",
                    conversation_id=inbound.conversation_id,
                    source_message_id=inbound.message_id,
                    user_id=inbound.user_id,
                    status="succeeded",
                    external_id="123",
                )
            )
            await session.commit()

        result = await QualityService(factory).metrics(days=30)
        values = {item["key"]: item for item in result["metrics"]}
        assert values["tool_success_rate"]["value"] == 50
        assert values["issue_success_rate"]["value"] == 100
        assert values["citation_coverage"]["value"] == 100
        assert values["event_dedup_rate"]["value"] == 100
        assert values["context_issue_success_rate"]["value"] == 100
        assert values["positive_feedback_rate"]["value"] == 100
        assert values["p95_response_ms"]["value"] == 1200
        assert result["tool_breakdown"][0]["tool_name"] == "github_get_file"
        assert result["tool_breakdown"][0]["failed"] == 1
        assert result["failure_categories"][0]["category"] == "validation"
        latency = {item["stage"]: item for item in result["latency_breakdown"]}
        assert latency["llm_step"]["p95_ms"] == 200
        assert latency["tool_step"]["average_ms"] == 30
    finally:
        await engine.dispose()


async def test_builtin_benchmark_has_twenty_reproducible_cases() -> None:
    result = await run_benchmark()
    recall = next(item for item in result["metrics"] if item["key"] == "rag_recall_at_5")
    assert recall["denominator"] == 20
    assert recall["value"] >= 80
    assert len(result["rag_cases"]) == 20
