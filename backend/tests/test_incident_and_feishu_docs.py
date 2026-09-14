import httpx
import pytest
from sqlalchemy import select

from app.db.models import Tenant, User
from app.db.session import create_engine, create_session_factory, create_tables
from app.rag.embedding import DevelopmentHashEmbeddingProvider
from app.services.feishu_document_service import (
    FeishuDocumentError,
    FeishuDocumentService,
)
from app.services.incident_service import IncidentService
from app.services.knowledge_service import KnowledgeService
from app.services.permission_service import PermissionDeniedError, PermissionService
from app.tools.context import ToolContext
from app.tools.incident import IncidentSaveArgs, IncidentSaveTool, IncidentSearchArgs, IncidentSearchTool


async def _identity(factory, tenant_key: str) -> tuple[int, int]:
    async with factory() as session:
        tenant = Tenant(external_key=tenant_key, name=tenant_key, status="active")
        session.add(tenant)
        await session.flush()
        user = User(tenant_id=tenant.id, name="Tester", role="lead")
        session.add(user)
        await session.commit()
        return tenant.id, user.id


async def test_incident_save_search_and_tenant_isolation(tmp_path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'incidents.db'}")
    await create_tables(engine)
    factory = create_session_factory(engine)
    tenant_a, user_a = await _identity(factory, "tenant-a")
    tenant_b, user_b = await _identity(factory, "tenant-b")
    service = IncidentService(factory)
    try:
        saved = await service.create(
            tenant_id=tenant_a,
            created_by_user_id=user_a,
            title="支付回调后订单未更新",
            summary="order-service 没有消费 PaymentSucceededEvent",
            severity="P1",
            service="order-service",
            error_code="E_PAY_402",
            evidence=["MQ lag 1200", "consumer error log"],
        )
        await service.create(
            tenant_id=tenant_b,
            created_by_user_id=user_b,
            title="另一个租户的故障",
            summary="private incident",
        )
        assert saved.incident_key == "INC-0001"
        results = await service.search(
            tenant_id=tenant_a, query="E_PAY_402", limit=10
        )
        assert [item.incident_key for item in results] == ["INC-0001"]
        assert results[0].evidence == ["MQ lag 1200", "consumer error log"]
        assert await service.search(tenant_id=tenant_a, query="private", limit=10) == []

        context = ToolContext(
            tenant_id=tenant_a,
            user_id=user_a,
            user_role="lead",
            conversation_id=1,
            source_message_id=1,
            external_message_id="om-1",
        )
        save_result = await IncidentSaveTool(service).run(
            context,
            IncidentSaveArgs(title="登录异常", summary="401", severity="P2"),
        )
        assert save_result.display_data["incident_key"] == "INC-0003"
        search_result = await IncidentSearchTool(service).run(
            context, IncidentSearchArgs(query="登录")
        )
        assert search_result.display_data["incidents"][0]["title"] == "登录异常"
    finally:
        await engine.dispose()


async def test_feishu_wiki_import_refresh_and_citation_url(tmp_path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'feishu-doc.db'}")
    await create_tables(engine)
    factory = create_session_factory(engine)
    tenant_id, _ = await _identity(factory, "tenant-feishu")
    knowledge = KnowledgeService(
        factory,
        DevelopmentHashEmbeddingProvider(dimensions=64),
        chunk_size=200,
        chunk_overlap=20,
        min_score=0.01,
    )
    raw_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal raw_calls
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t-token"})
        assert request.headers["authorization"] == "Bearer t-token"
        if request.url.path.endswith("/wiki/v2/spaces/get_node"):
            assert request.url.params["token"] == "wikcn12345"
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "node": {
                            "obj_type": "docx",
                            "obj_token": "doccn67890",
                            "title": "支付故障手册",
                        }
                    },
                },
            )
        if request.url.path.endswith("/docx/v1/documents/doccn67890/raw_content"):
            raw_calls += 1
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "content": f"支付回调排查：检查 PaymentSucceededEvent 和 MQ lag。版本 {raw_calls}"
                    },
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = FeishuDocumentService(
            app_id="cli_test",
            app_secret="secret",
            knowledge_service=knowledge,
            client=client,
        )
        source = "https://acme.feishu.cn/wiki/wikcn12345?from=space#top"
        first = await service.import_url(tenant_id=tenant_id, url=source)
        second = await service.import_url(tenant_id=tenant_id, url=source)

    try:
        assert first.document.title == "支付故障手册"
        assert first.source_url == "https://acme.feishu.cn/wiki/wikcn12345"
        assert second.replaced_versions == 1
        documents = await knowledge.list_documents(tenant_key="tenant-feishu")
        assert len(documents) == 1
        assert documents[0].id == second.document.id
        hits = await knowledge.search(
            tenant_id=tenant_id, query="PaymentSucceededEvent", top_k=5
        )
        assert hits[0].source_url == first.source_url
        assert "版本 2" in hits[0].content
    finally:
        await engine.dispose()


def test_feishu_import_rejects_non_feishu_and_applies_write_permissions() -> None:
    with pytest.raises(FeishuDocumentError):
        FeishuDocumentService._parse_url("https://example.com/docx/doccn12345")
    permissions = PermissionService()
    with pytest.raises(PermissionDeniedError):
        permissions.require(role="member", permission="knowledge_write")
    permissions.require(role="lead", permission="knowledge_write")
    permissions.require(role="member", permission="incident_write")
