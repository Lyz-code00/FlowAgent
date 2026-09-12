from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_health_and_url_verification(monkeypatch) -> None:
    monkeypatch.setenv("FLOWAGENT_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("FLOWAGENT_ADMIN_API_TOKEN", "test-admin-token")
    from app.core.config import get_settings

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
