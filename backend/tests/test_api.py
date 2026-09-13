from httpx import ASGITransport, AsyncClient

from app.main import app
from app.db.models import GitHubConfig, Message
from app.db.session import create_session_factory
from app.services.github_service import GitHubIssue
from app.schemas.message import UnifiedMessage
from app.tools.context import ToolContext


class FakeSummaryGitHubService:
    def __init__(self) -> None:
        self.create_calls = 0

    async def create_issue(self, **kwargs) -> GitHubIssue:
        self.create_calls += 1
        return GitHubIssue(
            number=88,
            title=kwargs["title"],
            state="open",
            html_url="https://github.test/issues/88",
            body=kwargs["body"],
            labels=kwargs["labels"],
        )

    async def check_connection(self) -> dict:
        return {
            "connected": True,
            "full_name": "acme/flowagent",
            "private": True,
            "default_branch": "main",
        }


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
        factory = create_session_factory(app.state.db_engine)
        async with factory() as session:
            assistant_message = Message(
                conversation_id=inbound.conversation_id,
                role="assistant",
                content="服务当前运行正常。",
            )
            session.add(assistant_message)
            await session.commit()
            await session.refresh(assistant_message)
            assistant_message_id = assistant_message.id
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
            assert edited.json()["status"] == "draft"

            blocked = await client.post(
                f"/api/v1/summaries/{summaries.json()[0]['id']}/actions/0/github-issue",
                headers=headers,
            )
            assert blocked.status_code == 409

            confirmed = await client.post(
                f"/api/v1/summaries/{summaries.json()[0]['id']}/confirm",
                headers=headers,
            )
            assert confirmed.status_code == 200
            assert confirmed.json()["status"] == "confirmed"

            fake_github = FakeSummaryGitHubService()

            async def fake_github_resolver():
                return fake_github

            app.state.github_service_resolver = fake_github_resolver
            issue_path = (
                f"/api/v1/summaries/{summaries.json()[0]['id']}"
                "/actions/0/github-issue"
            )
            created_issue = await client.post(issue_path, headers=headers)
            replayed_issue = await client.post(issue_path, headers=headers)
            assert created_issue.status_code == 200
            assert replayed_issue.json()["number"] == 88
            assert fake_github.create_calls == 1

            refreshed = await client.get("/api/v1/summaries", headers=headers)
            assert refreshed.json()[0]["action_items"][0]["github_issue"]["number"] == 88

            github_config = await client.get("/api/v1/github/config", headers=headers)
            assert github_config.status_code == 200
            assert "token" not in github_config.json()
            changed_github = await client.put(
                "/api/v1/github/config",
                headers=headers,
                json={
                    "owner": "acme",
                    "repo": "flowagent",
                    "token": "new-secret-token",
                    "clear_token": False,
                    "default_labels": ["bug", "P1", "bug"],
                    "default_assignee": "octocat",
                    "member_can_create_issue": True,
                },
            )
            assert changed_github.status_code == 200
            assert changed_github.json()["default_labels"] == ["bug", "P1"]
            assert changed_github.json()["token_configured"] is True
            assert "token" not in changed_github.json()

            connection = await client.post("/api/v1/github/config/test", headers=headers)
            assert connection.status_code == 200
            assert connection.json()["full_name"] == "acme/flowagent"

            feedback = await client.put(
                f"/api/v1/messages/{assistant_message_id}/feedback",
                headers=headers,
                json={"rating": "negative", "reason": "缺少健康检查数据"},
            )
            assert feedback.status_code == 200
            assert feedback.json()["rating"] == "negative"
            feedback_again = await client.put(
                f"/api/v1/messages/{assistant_message_id}/feedback",
                headers=headers,
                json={"rating": "positive", "reason": None},
            )
            assert feedback_again.status_code == 200
            listed_feedback = await client.get(
                "/api/v1/feedback?rating=positive", headers=headers
            )
            assert listed_feedback.status_code == 200
            assert listed_feedback.json()[0]["message_id"] == assistant_message_id
            detail = await client.get(
                f"/api/v1/conversations/{inbound.conversation_id}", headers=headers
            )
            assistant = next(
                message
                for message in detail.json()["messages"]
                if message["id"] == assistant_message_id
            )
            assert assistant["feedback"]["rating"] == "positive"
            trace_stream = await client.get(
                f"/api/v1/conversations/{inbound.conversation_id}/traces/stream?once=true",
                headers=headers,
            )
            assert trace_stream.status_code == 200
            assert trace_stream.headers["content-type"].startswith("text/event-stream")
            assert "event: traces" in trace_stream.text

            async with factory() as session:
                stored_github = await session.get(GitHubConfig, 1)
                assert stored_github is not None
                assert "new-secret-token" not in stored_github.token_encrypted

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
