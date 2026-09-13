import httpx

from app.db.session import create_engine, create_session_factory, create_tables
from app.rag.chunker import chunk_sections
from app.rag.embedding import (
    DevelopmentHashEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
from app.rag.parser import ExtractedSection, parse_document
from app.services.knowledge_service import KnowledgeService
from app.services.knowledge_service import SearchHit
from app.tools.context import ToolContext
from app.tools.knowledge import KnowledgeSearchArgs, KnowledgeSearchTool


def test_markdown_parser_and_chunk_overlap() -> None:
    sections = parse_document(
        "guide.md",
        "# Login\n401 means the token is invalid.\n\n## Fix\nRefresh the token.".encode(),
    )
    assert [section.locator for section in sections] == ["Login", "Fix"]

    chunks = chunk_sections(
        [ExtractedSection(text="A" * 180 + "\n\n" + "B" * 180, locator="long")],
        chunk_size=220,
        overlap=40,
    )
    assert len(chunks) == 2
    assert chunks[0].index == 0
    assert chunks[1].index == 1
    assert chunks[0].locator.startswith("long, chars")


async def test_openai_compatible_embedding_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        assert payload == {
            "model": "embedding-model",
            "input": ["first", "second"],
            "encoding_format": "float",
            "dimensions": 3,
        }
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0, 0.0]},
                    {"index": 0, "embedding": [1.0, 0.0, 0.0]},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleEmbeddingProvider(
            base_url="https://embedding.example/v1",
            api_key="key",
            model="embedding-model",
            dimensions=3,
            client=client,
        )
        vectors = await provider.embed(["first", "second"])
    assert vectors == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


async def test_ingest_search_citation_tenant_isolation_and_delete(tmp_path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'knowledge.db'}")
    await create_tables(engine)
    factory = create_session_factory(engine)
    service = KnowledgeService(
        factory,
        DevelopmentHashEmbeddingProvider(dimensions=64),
        chunk_size=120,
        chunk_overlap=20,
        min_score=0.01,
    )
    try:
        first = await service.ingest(
            tenant_key="tenant-a",
            filename="payments.md",
            data=(
                "# Payment callback\n"
                "PaymentSucceededEvent updates the order status. "
                "If the order remains pending, inspect the order consumer and MQ lag."
            ).encode(),
            content_type="text/markdown",
        )
        await service.ingest(
            tenant_key="tenant-b",
            filename="private.txt",
            data=b"payment callback secret for another tenant",
            content_type="text/plain",
        )

        from app.db.models import Tenant
        from sqlalchemy import select

        async with factory() as session:
            tenant_a = await session.scalar(
                select(Tenant).where(Tenant.external_key == "tenant-a")
            )
            assert tenant_a is not None
            tenant_a_id = tenant_a.id

        hits = await service.search(
            tenant_id=tenant_a_id,
            query="payment callback order consumer",
            top_k=5,
        )
        assert hits
        assert hits[0].citation_id == 1
        assert hits[0].source_name == "payments.md"
        assert all(hit.source_name != "private.txt" for hit in hits)

        documents = await service.list_documents(tenant_key="tenant-a")
        assert documents == [first]
        assert await service.delete_document(
            tenant_key="tenant-b", document_id=first.id
        ) is False
        assert await service.delete_document(
            tenant_key="tenant-a", document_id=first.id
        ) is True
        assert await service.list_documents(tenant_key="tenant-a") == []
    finally:
        await engine.dispose()


async def test_knowledge_tool_returns_citation_contract() -> None:
    class FakeKnowledgeService:
        async def search(self, **kwargs):
            return [
                SearchHit(
                    citation_id=1,
                    document_id=7,
                    title="Login guide",
                    source_name="login.md",
                    source_locator="401, chars 1-80",
                    content="Refresh an expired access token.",
                    score=0.91,
                )
            ]

    tool = KnowledgeSearchTool(FakeKnowledgeService(), default_top_k=4)  # type: ignore[arg-type]
    result = await tool.run(
        ToolContext(
            tenant_id=1,
            user_id=1,
            user_role="member",
            conversation_id=1,
            source_message_id=1,
            external_message_id="om-1",
        ),
        KnowledgeSearchArgs(query="login 401"),
    )

    assert result.success is True
    assert result.display_data["results"][0]["citation_id"] == 1
    assert "[citation_id]" in result.llm_content


def test_bm25_prioritizes_exact_technical_terms_and_chinese_phrases() -> None:
    documents = [
        "常规登录说明与用户帮助文档。",
        "支付回调 PaymentSucceededEvent 失败时检查 MQ lag 和错误码 E_PAY_402。",
        "订单列表分页接口说明。",
    ]
    scores = KnowledgeService._bm25_scores(
        "支付回调 E_PAY_402",
        documents,
    )
    assert scores[1] > scores[0]
    assert scores[1] > scores[2]
    assert scores[1] > 0
