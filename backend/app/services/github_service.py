import re
from typing import Any

import httpx
from pydantic import BaseModel, Field


class GitHubError(RuntimeError):
    pass


class GitHubConfigurationError(GitHubError):
    pass


class GitHubAuthenticationError(GitHubError):
    pass


class GitHubRateLimitError(GitHubError):
    def __init__(self, message: str, *, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class GitHubIssue(BaseModel):
    number: int
    title: str
    state: str
    html_url: str
    body: str | None = None
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)


class GitHubService:
    def __init__(
        self,
        *,
        token: str,
        owner: str,
        repo: str,
        base_url: str = "https://api.github.com",
        api_version: str = "2026-03-10",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = token
        self.owner = owner
        self.repo = repo
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self._client = client

    async def search_issues(
        self, *, query: str, state: str = "all", labels: list[str] | None = None
    ) -> list[GitHubIssue]:
        if re.search(r"(?:^|\s)(?:repo|org|user):", query, re.IGNORECASE):
            raise GitHubError(
                "repository, organization and user qualifiers are not allowed"
            )
        if any('"' in label or "\n" in label for label in labels or []):
            raise GitHubError("labels cannot contain quotes or newlines")
        qualifiers = [query, f"repo:{self.owner}/{self.repo}", "is:issue"]
        if state != "all":
            qualifiers.append(f"state:{state}")
        qualifiers.extend(f'label:"{label}"' for label in labels or [])
        data = await self._request(
            "GET",
            "/search/issues",
            params={"q": " ".join(qualifiers), "per_page": 10},
        )
        return [
            self._parse_issue(item)
            for item in data.get("items", [])
            if "pull_request" not in item
        ]

    async def get_issue(self, issue_number: int) -> GitHubIssue:
        data = await self._request(
            "GET", f"/repos/{self.owner}/{self.repo}/issues/{issue_number}"
        )
        if "pull_request" in data:
            raise GitHubError(f"#{issue_number} is a pull request, not an issue")
        return self._parse_issue(data)

    async def create_issue(
        self,
        *,
        title: str,
        body: str,
        labels: list[str],
        assignee: str | None = None,
    ) -> GitHubIssue:
        payload: dict[str, Any] = {"title": title, "body": body, "labels": labels}
        if assignee:
            payload["assignees"] = [assignee]
        data = await self._request(
            "POST", f"/repos/{self.owner}/{self.repo}/issues", json=payload
        )
        return self._parse_issue(data)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self._require_configuration()
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=20)
        try:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.token}",
                    "X-GitHub-Api-Version": self.api_version,
                    "User-Agent": "FlowAgent",
                },
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            raise GitHubError("GitHub API request timed out") from exc
        except httpx.HTTPError as exc:
            raise GitHubError("GitHub API request failed") from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code in {403, 429} and (
            response.headers.get("x-ratelimit-remaining") == "0"
            or "rate limit" in response.text.lower()
        ):
            retry_after = response.headers.get("retry-after") or response.headers.get(
                "x-ratelimit-reset"
            )
            raise GitHubRateLimitError(
                "GitHub API rate limit exceeded", retry_after=retry_after
            )
        if response.status_code in {401, 403}:
            raise GitHubAuthenticationError(
                "GitHub authentication failed or the token lacks permission"
            )
        if response.status_code >= 400:
            message = "unknown error"
            try:
                message = str(response.json().get("message") or message)
            except ValueError:
                pass
            raise GitHubError(f"GitHub API returned {response.status_code}: {message}")
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubError("GitHub API returned invalid JSON") from exc

    def _require_configuration(self) -> None:
        if not self.token or not self.owner or not self.repo:
            raise GitHubConfigurationError(
                "GitHub token, owner and repository must be configured"
            )

    @staticmethod
    def _parse_issue(data: dict[str, Any]) -> GitHubIssue:
        labels = [
            item.get("name", "") if isinstance(item, dict) else str(item)
            for item in data.get("labels") or []
        ]
        assignees = [
            item.get("login", "")
            for item in data.get("assignees") or []
            if isinstance(item, dict)
        ]
        return GitHubIssue(
            number=data["number"],
            title=data["title"],
            state=data["state"],
            html_url=data["html_url"],
            body=data.get("body"),
            labels=[item for item in labels if item],
            assignees=[item for item in assignees if item],
        )
