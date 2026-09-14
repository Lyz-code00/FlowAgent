import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any
from urllib.parse import quote

import httpx


class ObservabilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class HealthResult:
    service: str
    healthy: bool
    status_code: int | None
    latency_ms: int
    checked_at: str
    detail: str


class ObservabilityService:
    def __init__(
        self,
        *,
        health_urls: dict[str, str] | None = None,
        prometheus_url: str = "",
        prometheus_token: str = "",
        loki_url: str = "",
        loki_token: str = "",
        sentry_url: str = "https://sentry.io/api/0",
        sentry_token: str = "",
        sentry_org: str = "",
        sentry_project: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.health_urls = {
            key.strip(): value.rstrip("/")
            for key, value in (health_urls or {}).items()
            if key.strip() and value.strip()
        }
        self.prometheus_url = prometheus_url.rstrip("/")
        self.prometheus_token = prometheus_token
        self.loki_url = loki_url.rstrip("/")
        self.loki_token = loki_token
        self.sentry_url = sentry_url.rstrip("/")
        self.sentry_token = sentry_token
        self.sentry_org = sentry_org
        self.sentry_project = sentry_project
        self._client = client

    def capabilities(self) -> dict[str, Any]:
        return {
            "health_services": sorted(self.health_urls),
            "prometheus": bool(self.prometheus_url),
            "loki": bool(self.loki_url),
            "sentry": bool(
                self.sentry_token and self.sentry_org and self.sentry_project
            ),
        }

    async def health(self, *, service: str | None = None) -> list[HealthResult]:
        targets = self.health_urls
        if service:
            if service not in targets:
                raise ObservabilityError(
                    f"未配置服务 {service}；可查询：{', '.join(sorted(targets)) or '无'}"
                )
            targets = {service: targets[service]}
        if not targets:
            raise ObservabilityError("未配置服务健康检查地址")
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=8, follow_redirects=False)
        results: list[HealthResult] = []
        try:
            for name, url in targets.items():
                started = monotonic()
                checked_at = datetime.now(timezone.utc).isoformat()
                try:
                    response = await client.get(url)
                    detail = response.text[:500].strip()
                    results.append(
                        HealthResult(
                            service=name,
                            healthy=200 <= response.status_code < 400,
                            status_code=response.status_code,
                            latency_ms=round((monotonic() - started) * 1000),
                            checked_at=checked_at,
                            detail=detail,
                        )
                    )
                except httpx.HTTPError as exc:
                    results.append(
                        HealthResult(
                            service=name,
                            healthy=False,
                            status_code=None,
                            latency_ms=round((monotonic() - started) * 1000),
                            checked_at=checked_at,
                            detail=str(exc)[:500],
                        )
                    )
        finally:
            if owns_client:
                await client.aclose()
        return results

    async def prometheus_query(self, *, query: str, time: str | None = None) -> dict:
        if not self.prometheus_url:
            raise ObservabilityError("未配置 Prometheus 查询地址")
        data = await self._get_json(
            f"{self.prometheus_url}/api/v1/query",
            token=self.prometheus_token,
            params={"query": query, **({"time": time} if time else {})},
        )
        if data.get("status") != "success":
            raise ObservabilityError("Prometheus 查询未成功")
        result = data.get("data", {}).get("result", [])
        if not isinstance(result, list):
            raise ObservabilityError("Prometheus 响应格式无效")
        return {
            "query": query,
            "result_type": data.get("data", {}).get("resultType"),
            "result": result[:100],
            "queried_at": datetime.now(timezone.utc).isoformat(),
        }

    async def loki_search(
        self, *, query: str, minutes: int = 30, limit: int = 100
    ) -> dict:
        if not self.loki_url:
            raise ObservabilityError("未配置 Loki 查询地址")
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=minutes)
        data = await self._get_json(
            f"{self.loki_url}/loki/api/v1/query_range",
            token=self.loki_token,
            params={
                "query": query,
                "start": str(int(start.timestamp() * 1_000_000_000)),
                "end": str(int(end.timestamp() * 1_000_000_000)),
                "limit": str(limit),
                "direction": "backward",
            },
        )
        if data.get("status") != "success":
            raise ObservabilityError("Loki 查询未成功")
        streams = data.get("data", {}).get("result", [])
        return {
            "query": query,
            "window_minutes": minutes,
            "streams": streams[:100] if isinstance(streams, list) else [],
            "queried_at": end.isoformat(),
        }

    async def sentry_search(self, *, query: str, limit: int = 20) -> dict:
        if not (self.sentry_token and self.sentry_org and self.sentry_project):
            raise ObservabilityError("未完整配置 Sentry token、组织和项目")
        url = (
            f"{self.sentry_url}/projects/{quote(self.sentry_org, safe='')}"
            f"/{quote(self.sentry_project, safe='')}/issues/"
        )
        data = await self._get_json(
            url,
            token=self.sentry_token,
            params={"query": query, "limit": str(limit), "sort": "date"},
        )
        if not isinstance(data, list):
            raise ObservabilityError("Sentry 响应格式无效")
        fields = (
            "id",
            "shortId",
            "title",
            "culprit",
            "level",
            "status",
            "count",
            "userCount",
            "firstSeen",
            "lastSeen",
            "permalink",
        )
        return {
            "query": query,
            "issues": [
                {field: item.get(field) for field in fields}
                for item in data[:limit]
                if isinstance(item, dict)
            ],
            "queried_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _get_json(
        self,
        url: str,
        *,
        token: str,
        params: dict[str, str],
    ) -> Any:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=15, follow_redirects=False)
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            if len(response.content) > 2 * 1024 * 1024:
                raise ObservabilityError("监控接口响应超过 2 MiB 限制")
            return json.loads(response.content)
        except (httpx.HTTPError, ValueError) as exc:
            raise ObservabilityError("监控接口请求失败") from exc
        finally:
            if owns_client:
                await client.aclose()
