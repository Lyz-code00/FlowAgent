import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.services.knowledge_service import DocumentInfo, KnowledgeService


@dataclass(frozen=True)
class FeishuDocumentImport:
    document: DocumentInfo
    source_url: str
    document_token: str
    replaced_versions: int


class FeishuDocumentError(RuntimeError):
    pass


class FeishuDocumentService:
    API_BASE = "https://open.feishu.cn/open-apis"
    TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{5,128}$")
    ALLOWED_HOST_SUFFIXES = ("feishu.cn", "larksuite.com")

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        knowledge_service: KnowledgeService,
        max_chars: int = 500_000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.knowledge_service = knowledge_service
        self.max_chars = max_chars
        self._client = client

    async def import_url(
        self, *, tenant_id: int, url: str, title: str | None = None
    ) -> FeishuDocumentImport:
        if not self.app_id or not self.app_secret:
            raise FeishuDocumentError("飞书应用凭据未配置")
        kind, token = self._parse_url(url)
        canonical_url = self._canonical_url(url)
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=20, follow_redirects=False)
        try:
            access_token = await self._tenant_access_token(client)
            resolved_title: str | None = None
            document_token = token
            if kind == "wiki":
                node_data = await self._get_json(
                    client,
                    f"{self.API_BASE}/wiki/v2/spaces/get_node",
                    access_token,
                    params={"token": token},
                )
                node = node_data.get("node") or {}
                object_type = str(node.get("obj_type") or "")
                if object_type != "docx":
                    raise FeishuDocumentError(
                        f"当前仅支持飞书新版文档（docx），该 Wiki 节点类型为 {object_type or '未知'}"
                    )
                document_token = str(node.get("obj_token") or "")
                resolved_title = str(node.get("title") or "").strip() or None
                self._validate_token(document_token)

            raw_data = await self._get_json(
                client,
                f"{self.API_BASE}/docx/v1/documents/{document_token}/raw_content",
                access_token,
            )
            content = str(raw_data.get("content") or "").strip()
            if not content:
                raise FeishuDocumentError("飞书文档没有可索引的文本内容")
            if len(content) > self.max_chars:
                raise FeishuDocumentError(
                    f"飞书文档超过 {self.max_chars} 字符限制"
                )
            document_title = (
                (title or "").strip()
                or resolved_title
                or next((line.strip("# ") for line in content.splitlines() if line.strip()), "")
                or f"飞书文档 {document_token}"
            )[:512]
            document = await self.knowledge_service.ingest_for_tenant_id(
                tenant_id=tenant_id,
                filename=f"feishu-{document_token}.txt",
                data=content.encode("utf-8"),
                content_type="text/plain",
                title=document_title,
                source_url=canonical_url,
            )
            replaced = await self.knowledge_service.replace_source_versions(
                tenant_id=tenant_id,
                source_url=canonical_url,
                keep_document_id=document.id,
            )
            return FeishuDocumentImport(
                document=document,
                source_url=canonical_url,
                document_token=document_token,
                replaced_versions=replaced,
            )
        finally:
            if owns_client:
                await client.aclose()

    async def _tenant_access_token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            f"{self.API_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        data = self._response_json(response)
        token = str(data.get("tenant_access_token") or "")
        if not token:
            raise FeishuDocumentError("飞书未返回 tenant_access_token")
        return token

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        access_token: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )
        data = self._response_json(response)
        payload = data.get("data")
        if not isinstance(payload, dict):
            raise FeishuDocumentError("飞书接口响应缺少 data")
        return payload

    @staticmethod
    def _response_json(response: httpx.Response) -> dict:
        try:
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FeishuDocumentError("飞书接口请求失败") from exc
        if not isinstance(data, dict):
            raise FeishuDocumentError("飞书接口返回格式无效")
        if data.get("code") not in (None, 0):
            message = str(data.get("msg") or "未知错误")
            raise FeishuDocumentError(f"飞书接口拒绝请求：{message}")
        return data

    @classmethod
    def _parse_url(cls, url: str) -> tuple[str, str]:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or not any(
            host == suffix or host.endswith(f".{suffix}")
            for suffix in cls.ALLOWED_HOST_SUFFIXES
        ):
            raise FeishuDocumentError("只允许导入 HTTPS 飞书/Lark 文档链接")
        segments = [segment for segment in parsed.path.split("/") if segment]
        for kind in ("wiki", "docx"):
            if kind in segments:
                index = segments.index(kind)
                if index + 1 < len(segments):
                    token = segments[index + 1]
                    cls._validate_token(token)
                    return kind, token
        raise FeishuDocumentError("链接中未找到 /wiki/{token} 或 /docx/{token}")

    @classmethod
    def _validate_token(cls, token: str) -> None:
        if not cls.TOKEN_PATTERN.fullmatch(token):
            raise FeishuDocumentError("飞书文档 token 格式无效")

    @staticmethod
    def _canonical_url(url: str) -> str:
        parsed = urlparse(url.strip())
        return parsed._replace(query="", fragment="").geturl()
