import base64
import binascii
import re
from typing import Any
from urllib.parse import quote

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


class GitHubChange(BaseModel):
    kind: str
    identifier: str
    title: str
    author: str | None = None
    state: str | None = None
    html_url: str
    updated_at: str | None = None


class GitHubChangedFile(BaseModel):
    filename: str
    status: str
    additions: int = 0
    deletions: int = 0
    changes: int = 0
    patch: str | None = None
    blob_url: str | None = None
    raw_url: str | None = None
    patch_truncated: bool = False


class GitHubCommitDetail(BaseModel):
    sha: str
    message: str
    author: str | None = None
    committed_at: str | None = None
    html_url: str
    additions: int = 0
    deletions: int = 0
    total_changes: int = 0
    files: list[GitHubChangedFile] = Field(default_factory=list)
    files_truncated: bool = False


class GitHubPullRequestChanges(BaseModel):
    number: int
    title: str
    state: str
    merged: bool = False
    author: str | None = None
    base_ref: str
    head_ref: str
    body: str | None = None
    html_url: str
    files: list[GitHubChangedFile] = Field(default_factory=list)
    files_truncated: bool = False


class GitHubComparison(BaseModel):
    status: str
    ahead_by: int = 0
    behind_by: int = 0
    total_commits: int = 0
    html_url: str
    files: list[GitHubChangedFile] = Field(default_factory=list)
    files_truncated: bool = False


class GitHubFileContent(BaseModel):
    path: str
    ref: str | None = None
    sha: str
    size: int
    html_url: str
    content: str
    content_truncated: bool = False


class GitHubRelease(BaseModel):
    tag_name: str
    name: str
    html_url: str
    author: str | None = None
    target_commitish: str | None = None
    draft: bool = False
    prerelease: bool = False
    published_at: str | None = None
    body: str | None = None


class GitHubComment(BaseModel):
    id: int
    html_url: str
    body: str
    author: str | None = None
    created_at: str | None = None


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

    async def update_issue(
        self,
        *,
        issue_number: int,
        title: str | None = None,
        body: str | None = None,
        labels: list[str] | None = None,
    ) -> GitHubIssue:
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if labels is not None:
            payload["labels"] = labels
        if not payload:
            raise GitHubError("at least one issue field is required")
        data = await self._request(
            "PATCH",
            f"/repos/{self.owner}/{self.repo}/issues/{issue_number}",
            json=payload,
        )
        return self._parse_issue(data)

    async def close_issue(
        self, *, issue_number: int, state_reason: str = "completed"
    ) -> GitHubIssue:
        data = await self._request(
            "PATCH",
            f"/repos/{self.owner}/{self.repo}/issues/{issue_number}",
            json={"state": "closed", "state_reason": state_reason},
        )
        return self._parse_issue(data)

    async def assign_issue(
        self, *, issue_number: int, assignees: list[str]
    ) -> GitHubIssue:
        data = await self._request(
            "PATCH",
            f"/repos/{self.owner}/{self.repo}/issues/{issue_number}",
            json={"assignees": assignees},
        )
        return self._parse_issue(data)

    async def add_issue_comment(
        self, *, issue_number: int, body: str
    ) -> GitHubComment:
        data = await self._request(
            "POST",
            f"/repos/{self.owner}/{self.repo}/issues/{issue_number}/comments",
            json={"body": body},
        )
        return GitHubComment(
            id=int(data.get("id") or 0),
            html_url=str(data.get("html_url") or ""),
            body=str(data.get("body") or body),
            author=(data.get("user") or {}).get("login"),
            created_at=data.get("created_at"),
        )

    async def check_connection(self) -> dict[str, Any]:
        data = await self._request("GET", f"/repos/{self.owner}/{self.repo}")
        return {
            "connected": True,
            "full_name": data.get("full_name") or f"{self.owner}/{self.repo}",
            "private": bool(data.get("private")),
            "default_branch": data.get("default_branch"),
        }

    async def recent_changes(self, *, limit: int = 10) -> list[GitHubChange]:
        page_size = max(1, min(limit, 20))
        commits = await self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/commits",
            params={"per_page": page_size},
        )
        pulls = await self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/pulls",
            params={
                "state": "all",
                "sort": "updated",
                "direction": "desc",
                "per_page": page_size,
            },
        )
        changes = [
            GitHubChange(
                kind="commit",
                identifier=str(item.get("sha", ""))[:7],
                title=str((item.get("commit") or {}).get("message") or "").splitlines()[0],
                author=(item.get("author") or {}).get("login")
                or (item.get("commit") or {}).get("author", {}).get("name"),
                html_url=str(item.get("html_url") or ""),
                updated_at=(item.get("commit") or {}).get("author", {}).get("date"),
            )
            for item in commits
        ]
        changes.extend(
            GitHubChange(
                kind="pull_request",
                identifier=f"#{item.get('number')}",
                title=str(item.get("title") or ""),
                author=(item.get("user") or {}).get("login"),
                state=item.get("state"),
                html_url=str(item.get("html_url") or ""),
                updated_at=item.get("updated_at"),
            )
            for item in pulls
        )
        changes.sort(key=lambda item: item.updated_at or "", reverse=True)
        return changes[:page_size]

    async def get_file(
        self, *, path: str, ref: str | None = None, max_chars: int = 50_000
    ) -> GitHubFileContent:
        normalized_path = self._validate_repository_path(path)
        data = await self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/contents/{quote(normalized_path, safe='/')}",
            params={"ref": ref} if ref else None,
        )
        if not isinstance(data, dict) or data.get("type") != "file":
            raise GitHubError(f"'{normalized_path}' is not a file")
        if data.get("encoding") != "base64" or not data.get("content"):
            raise GitHubError(
                "GitHub did not return inline file content; the file may be too large"
            )
        try:
            encoded = re.sub(r"\s+", "", str(data["content"]))
            raw = base64.b64decode(encoded, validate=True)
            decoded = raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise GitHubError("repository file is binary or not valid UTF-8 text") from exc
        truncated = len(decoded) > max_chars
        return GitHubFileContent(
            path=str(data.get("path") or normalized_path),
            ref=ref,
            sha=str(data.get("sha") or ""),
            size=int(data.get("size") or len(raw)),
            html_url=str(data.get("html_url") or ""),
            content=decoded[:max_chars],
            content_truncated=truncated,
        )

    async def get_commit(
        self, *, ref: str, max_files: int = 20, max_patch_chars: int = 12_000
    ) -> GitHubCommitDetail:
        safe_ref = self._validate_ref(ref)
        data = await self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/commits/{quote(safe_ref, safe='')}",
            params={"per_page": max_files},
        )
        all_files = data.get("files") or []
        commit = data.get("commit") or {}
        author = data.get("author") or {}
        git_author = commit.get("author") or {}
        stats = data.get("stats") or {}
        return GitHubCommitDetail(
            sha=str(data.get("sha") or safe_ref),
            message=str(commit.get("message") or ""),
            author=author.get("login") or git_author.get("name"),
            committed_at=git_author.get("date"),
            html_url=str(data.get("html_url") or ""),
            additions=int(stats.get("additions") or 0),
            deletions=int(stats.get("deletions") or 0),
            total_changes=int(stats.get("total") or 0),
            files=self._parse_changed_files(
                all_files[:max_files], max_patch_chars=max_patch_chars
            ),
            files_truncated=len(all_files) > max_files,
        )

    async def get_pull_request_changes(
        self,
        *,
        pull_number: int,
        max_files: int = 30,
        max_patch_chars: int = 12_000,
    ) -> GitHubPullRequestChanges:
        pull = await self._request(
            "GET", f"/repos/{self.owner}/{self.repo}/pulls/{pull_number}"
        )
        files = await self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/pulls/{pull_number}/files",
            params={"per_page": max_files},
        )
        base = pull.get("base") or {}
        head = pull.get("head") or {}
        return GitHubPullRequestChanges(
            number=int(pull.get("number") or pull_number),
            title=str(pull.get("title") or ""),
            state=str(pull.get("state") or "unknown"),
            merged=bool(pull.get("merged")),
            author=(pull.get("user") or {}).get("login"),
            base_ref=str(base.get("ref") or ""),
            head_ref=str(head.get("ref") or ""),
            body=pull.get("body"),
            html_url=str(pull.get("html_url") or ""),
            files=self._parse_changed_files(
                files[:max_files], max_patch_chars=max_patch_chars
            ),
            files_truncated=(int(pull.get("changed_files") or len(files)) > len(files)),
        )

    async def compare(
        self,
        *,
        base: str,
        head: str,
        max_files: int = 30,
        max_patch_chars: int = 12_000,
    ) -> GitHubComparison:
        safe_base = self._validate_ref(base)
        safe_head = self._validate_ref(head)
        data = await self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/compare/"
            f"{quote(safe_base, safe='')}...{quote(safe_head, safe='')}",
            params={"per_page": max_files},
        )
        files = data.get("files") or []
        return GitHubComparison(
            status=str(data.get("status") or "unknown"),
            ahead_by=int(data.get("ahead_by") or 0),
            behind_by=int(data.get("behind_by") or 0),
            total_commits=int(data.get("total_commits") or 0),
            html_url=str(data.get("html_url") or ""),
            files=self._parse_changed_files(
                files[:max_files], max_patch_chars=max_patch_chars
            ),
            files_truncated=len(files) > max_files,
        )

    async def list_releases(self, *, limit: int = 10) -> list[GitHubRelease]:
        data = await self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/releases",
            params={"per_page": max(1, min(limit, 20))},
        )
        return [
            GitHubRelease(
                tag_name=str(item.get("tag_name") or ""),
                name=str(item.get("name") or item.get("tag_name") or ""),
                html_url=str(item.get("html_url") or ""),
                author=(item.get("author") or {}).get("login"),
                target_commitish=item.get("target_commitish"),
                draft=bool(item.get("draft")),
                prerelease=bool(item.get("prerelease")),
                published_at=item.get("published_at"),
                body=(str(item.get("body") or "")[:12_000] or None),
            )
            for item in data
        ]

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
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
    def _validate_ref(ref: str) -> str:
        value = ref.strip()
        if not value or len(value) > 255 or any(char in value for char in "\r\n\x00"):
            raise GitHubError("invalid Git reference")
        return value

    @staticmethod
    def _validate_repository_path(path: str) -> str:
        value = path.strip().lstrip("/")
        if (
            not value
            or len(value) > 1000
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or any(char in value for char in "\r\n\x00")
        ):
            raise GitHubError("invalid repository file path")
        return value

    @classmethod
    def _parse_changed_files(
        cls, items: list[dict[str, Any]], *, max_patch_chars: int
    ) -> list[GitHubChangedFile]:
        result: list[GitHubChangedFile] = []
        for item in items:
            patch = item.get("patch")
            patch_text = str(patch) if patch is not None else None
            truncated = bool(patch_text and len(patch_text) > max_patch_chars)
            result.append(
                GitHubChangedFile(
                    filename=str(item.get("filename") or ""),
                    status=str(item.get("status") or "unknown"),
                    additions=int(item.get("additions") or 0),
                    deletions=int(item.get("deletions") or 0),
                    changes=int(item.get("changes") or 0),
                    patch=(patch_text[:max_patch_chars] if patch_text else None),
                    blob_url=item.get("blob_url"),
                    raw_url=item.get("raw_url"),
                    patch_truncated=truncated,
                )
            )
        return result

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
