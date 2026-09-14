import httpx
import pytest

from app.services.observability_service import ObservabilityError, ObservabilityService
from app.tools.observability import MonitorMetricArgs, MonitorMetricTool
from app.tools.context import ToolContext


async def test_observability_read_only_integrations() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, text='{"status":"ok"}')
        if request.url.path == "/prom/api/v1/query":
            assert request.url.params["query"] == "kafka_consumer_lag"
            assert request.headers["authorization"] == "Bearer prom-token"
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [{"metric": {"topic": "payments"}, "value": [1, "12"]}],
                    },
                },
            )
        if request.url.path == "/loki/loki/api/v1/query_range":
            assert request.url.params["query"] == '{service="order"} |= "ERROR"'
            return httpx.Response(
                200,
                json={"status": "success", "data": {"result": [{"stream": {"service": "order"}, "values": []}]}},
            )
        if request.url.path == "/sentry/api/0/projects/acme/flowagent/issues/":
            assert request.url.params["query"] == "is:unresolved"
            assert request.headers["authorization"] == "Bearer sentry-token"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "1",
                        "shortId": "FLOW-1",
                        "title": "Payment callback failed",
                        "status": "unresolved",
                        "permalink": "https://sentry.example/issues/1",
                        "extraSecret": "must-not-leak",
                    }
                ],
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ObservabilityService(
            health_urls={"flowagent": "https://monitor.example/health"},
            prometheus_url="https://monitor.example/prom",
            prometheus_token="prom-token",
            loki_url="https://monitor.example/loki",
            sentry_url="https://monitor.example/sentry/api/0",
            sentry_token="sentry-token",
            sentry_org="acme",
            sentry_project="flowagent",
            client=client,
        )
        health = await service.health(service="flowagent")
        metrics = await service.prometheus_query(query="kafka_consumer_lag")
        logs = await service.loki_search(query='{service="order"} |= "ERROR"')
        errors = await service.sentry_search(query="is:unresolved")

        assert health[0].healthy is True
        assert metrics["result"][0]["value"][1] == "12"
        assert logs["streams"][0]["stream"]["service"] == "order"
        assert errors["issues"][0]["shortId"] == "FLOW-1"
        assert "extraSecret" not in errors["issues"][0]
        assert service.capabilities() == {
            "health_services": ["flowagent"],
            "prometheus": True,
            "loki": True,
            "sentry": True,
        }

        tool_result = await MonitorMetricTool(service).run(
            ToolContext(
                tenant_id=1,
                user_id=1,
                user_role="member",
                conversation_id=1,
                source_message_id=1,
                external_message_id="om-1",
            ),
            MonitorMetricArgs(query="kafka_consumer_lag"),
        )
        assert tool_result.success is True
        assert "kafka_consumer_lag" in tool_result.llm_content

    assert all("prom-token" not in str(request.url) for request in requests)


async def test_observability_requires_server_configuration() -> None:
    service = ObservabilityService()
    with pytest.raises(ObservabilityError, match="Prometheus"):
        await service.prometheus_query(query="up")
    with pytest.raises(ObservabilityError, match="健康检查"):
        await service.health()
