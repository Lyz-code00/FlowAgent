from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.message import UnifiedMessage
from app.tools.context import ToolContext


async def test_health_and_url_verification(monkeypatch) -> None:
    monkeypatch.setenv("FLOWAGENT_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("FLOWAGENT_ADMIN_API_TOKEN", "test-admin-token")
    from app.core.config import get_settings

    get_settings.cache_clear()


async def test_admin_can_list_users_and_update_role(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        "FLOWAGENT_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'users.db'}"
    )
    monkeypatch.setenv("FLOWAGENT_ADMIN_API_TOKEN", "test-admin-token")
    from app.core.config import get_settings

    get_settings.cache_clear()
    async with app.router.lifespan_context(app):
        inbound = await app.state.message_gateway.conversation_service.accept_inbound(
            UnifiedMessage(
                platform="feishu",
                tenant_id="tenant-a",
                external_user_id="ou-test-user",
                conversation_id="oc-test-chat",
                message_id="om-test-message",
                message_type="text",
                text="hello",
            )
        )
        assert inbound is not None
        transport = ASGITransport(app=app)
        headers = {"X-FlowAgent-Admin-Token": "test-admin-token"}
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            summary_context = ToolContext(
                tenant_id=inbound.tenant_id,
                user_id=inbound.user_id,
                user_role=inbound.role,
                conversation_id=inbound.conversation_id,
                source_message_id=inbound.message_id,
                external_message_id="om-test-message",
            )
            await app.state.summary_service.save(
                context=summary_context,
                summary="确认修复登录超时问题。",
                decisions=["使用连接池"],
                bugs=["登录接口偶发超时"],
                action_items=[
                    {
                        "content": "检查数据库连接池",
                        "owner": "后端负责人",
                        "due_date": "2026-09-15",
                        "priority": "P1",
                        "status": "pending",
                    }
                ],
            )
            await app.state.summary_service.save(
                context=summary_context,
                summary="确认修复登录超时问题。",
                decisions=["使用连接池"],
                bugs=["登录接口偶发超时"],
                action_items=[],
            )
            summaries = await client.get("/api/v1/summaries", headers=headers)
            assert summaries.status_code == 200
            assert len(summaries.json()) == 1
            assert summaries.json()[0]["decisions"] == ["使用连接池"]
            edited = await client.put(
                f"/api/v1/summaries/{summaries.json()[0]['id']}",
                headers=headers,
                json={
                    "summary": "登录超时问题待修复。",
                    "decisions": ["使用连接池"],
                    "bugs": ["登录接口偶发超时"],
                    "action_items": summaries.json()[0]["action_items"],
                },
            )
            assert edited.status_code == 200
            assert edited.json()["summary"] == "登录超时问题待修复。"

            agent_config = await client.get("/api/v1/agent/config", headers=headers)
            assert agent_config.status_code == 200
            assert agent_config.json()["knowledge_enabled"] is True

            updated_config = await client.put(
                "/api/v1/agent/config",
                headers=headers,
                json={
                    **agent_config.json(),
                    "name": "研发助手",
                    "model": "deepseek-chat-v2",
                    "max_steps": 7,
                    "github_enabled": False,
                },
            )
            assert updated_config.status_code == 200
            assert updated_config.json()["name"] == "研发助手"
            assert updated_config.json()["max_steps"] == 7
            assert updated_config.json()["github_enabled"] is False

            runtime = await client.get("/api/v1/config/runtime", headers=headers)
            assert runtime.status_code == 200
            assert runtime.json()["llm"]["model"] == "deepseek-chat-v2"
            assert runtime.json()["llm"]["max_steps"] == 7

            listed = await client.get("/api/v1/users", headers=headers)
            assert listed.status_code == 200
            users = listed.json()
            assert len(users) == 1
            assert users[0]["role"] == "member"
            assert users[0]["channels"] == [
                {"platform": "feishu", "external_user_id": "ou-test-user"}
            ]
            assert users[0]["message_count"] == 1

            tenants = await client.get("/api/v1/tenants", headers=headers)
            assert tenants.status_code == 200
            assert tenants.json() == [
                {
                    "id": 1,
                    "external_key": "tenant-a",
                    "name": "Tenant tenant-a",
                    "status": "active",
                    "user_count": 1,
                    "conversation_count": 1,
                    "document_count": 0,
                }
            ]

            updated = await client.put(
                f"/api/v1/users/{users[0]['id']}/role",
                headers=headers,
                json={"role": "lead"},
            )
            assert updated.status_code == 200
            assert updated.json()["role"] == "lead"

            invalid = await client.put(
                f"/api/v1/users/{users[0]['id']}/role",
                headers=headers,
                json={"role": "owner"},
            )
            assert invalid.status_code == 422
    get_settings.cache_clear()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/health")
            assert health.status_code == 200
            assert health.json() == {"status": "ok", "service": "flowagent"}

            challenge = await client.post(
                "/api/v1/channels/feishu/events",
                json={"type": "url_verification", "challenge": "challenge-code"},
            )
            assert challenge.status_code == 200
            assert challenge.json() == {"challenge": "challenge-code"}

            uploaded = await client.post(
                "/api/v1/knowledge/documents",
                headers={"X-FlowAgent-Admin-Token": "test-admin-token"},
                files={
                    "file": (
                        "guide.md",
                        b"# Login\nA 401 response means the access token is invalid.",
                        "text/markdown",
                    )
                },
            )
            assert uploaded.status_code == 201
            document = uploaded.json()
            assert document["status"] == "ready"
            assert document["chunk_count"] == 1

            listed = await client.get(
                "/api/v1/knowledge/documents",
                headers={"X-FlowAgent-Admin-Token": "test-admin-token"},
            )
            assert [item["id"] for item in listed.json()] == [document["id"]]

            deleted = await client.delete(
                f"/api/v1/knowledge/documents/{document['id']}",
                headers={"X-FlowAgent-Admin-Token": "test-admin-token"},
            )
            assert deleted.status_code == 204

            unauthorized = await client.get("/api/v1/dashboard/metrics")
            assert unauthorized.status_code == 401

            metrics = await client.get(
                "/api/v1/dashboard/metrics",
                headers={"X-FlowAgent-Admin-Token": "test-admin-token"},
            )
            assert metrics.status_code == 200
            assert metrics.json()["agent_runs_today"] == 0
    get_settings.cache_clear()
