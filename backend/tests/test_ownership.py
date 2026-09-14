from app.db.session import create_engine, create_session_factory, create_tables
from app.services.ownership_service import OwnershipService
from app.tools.context import ToolContext
from app.tools.ownership import OwnerLookupArgs, OwnerLookupTool

from test_incident_and_feishu_docs import _identity


async def test_ownership_mapping_lookup_and_tenant_isolation(tmp_path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'ownership.db'}")
    await create_tables(engine)
    factory = create_session_factory(engine)
    tenant_a, user_a = await _identity(factory, "tenant-a")
    tenant_b, _ = await _identity(factory, "tenant-b")
    service = OwnershipService(factory)
    try:
        owner = await service.create(
            tenant_id=tenant_a,
            service="order-service",
            team="后端平台组",
            display_name="张三",
            feishu_open_id="ou_zhangsan",
            github_username="zhangsan-gh",
        )
        await service.create(
            tenant_id=tenant_b,
            service="order-service",
            team="private team",
            github_username="private-user",
        )
        assert owner["tenant_key"] == "tenant-a"
        results = await service.search(tenant_id=tenant_a, query="后端", limit=10)
        assert [item.github_username for item in results] == ["zhangsan-gh"]
        assert await service.search(tenant_id=tenant_a, query="private", limit=10) == []

        context = ToolContext(
            tenant_id=tenant_a,
            user_id=user_a,
            user_role="member",
            conversation_id=1,
            source_message_id=1,
            external_message_id="om-1",
        )
        tool_result = await OwnerLookupTool(service).run(
            context, OwnerLookupArgs(query="order-service")
        )
        assert tool_result.display_data["owners"][0]["github_username"] == "zhangsan-gh"

        updated = await service.update(
            owner["id"],
            service="order-service",
            team="支付后端组",
            display_name="张三",
            feishu_open_id="ou_zhangsan",
            github_username="zhangsan-new",
            active=False,
        )
        assert updated is not None and updated["active"] is False
        assert await service.search(tenant_id=tenant_a, query="order", limit=10) == []
        assert await service.delete(owner["id"]) is True
        assert await service.delete(owner["id"]) is False
    finally:
        await engine.dispose()
