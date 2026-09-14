import asyncio
import ipaddress
import re
import socket
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from lxml import html
from pydantic import BaseModel, Field


class WebAccessError(RuntimeError):
    pass


class WebSearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class WebPage(BaseModel):
    title: str
    url: str
    content_type: str
    text: str
    text_truncated: bool = False


class WebService:
    SEARCH_URL = "https://html.duckduckgo.com/html/"
    USER_AGENT = (
        "Mozilla/5.0 (compatible; FlowAgent/1.0; "
        "+https://github.com/Lyz-code00/FlowAgent)"
    )
    ALLOWED_CONTENT_TYPES = {
        "text/html",
        "text/plain",
        "application/json",
        "application/xml",
        "text/xml",
    }

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        max_response_bytes: int = 1_000_000,
        timeout_seconds: float = 15,
        search_backend: str = "duckduckgo",
        search_api_key: str = "",
        search_base_url: str = "https://api.bochaai.com/v1/web-search",
    ) -> None:
        self._client = client
        self.max_response_bytes = max_response_bytes
        self.timeout_seconds = timeout_seconds
        self.search_backend = search_backend
        self.search_api_key = search_api_key
        self.search_base_url = search_base_url

    async def search(self, *, query: str, limit: int = 5) -> list[WebSearchResult]:
        if self.search_backend == "bocha":
            return await self._search_bocha(query=query, limit=limit)
        return await self._search_duckduckgo(query=query, limit=limit)

    async def _search_duckduckgo(
        self, *, query: str, limit: int
    ) -> list[WebSearchResult]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds, headers={"User-Agent": self.USER_AGENT}
        )
        try:
            response = await client.get(
                self.SEARCH_URL,
                params={"q": query},
                headers={"User-Agent": self.USER_AGENT},
            )
            response.raise_for_status()
            if len(response.content) > self.max_response_bytes:
                raise WebAccessError("web search response exceeded the size limit")
            document = html.fromstring(response.content)
            results: list[WebSearchResult] = []
            for node in document.xpath(
                '//*[contains(concat(" ", normalize-space(@class), " "), " result ")]'
            ):
                links = node.xpath(
                    './/a[contains(concat(" ", normalize-space(@class), " "), " result__a ")]'
                )
                if not links:
                    continue
                link = links[0]
                url = self._unwrap_search_url(str(link.get("href") or ""))
                if not url.startswith(("https://", "http://")):
                    continue
                snippets = node.xpath(
                    './/*[contains(concat(" ", normalize-space(@class), " "), " result__snippet ")]'
                )
                snippet = self._clean_text(
                    snippets[0].text_content() if snippets else ""
                )
                results.append(
                    WebSearchResult(
                        title=self._clean_text(link.text_content()),
                        url=url,
                        snippet=snippet,
                    )
                )
                if len(results) >= limit:
                    break
            return results
        except httpx.HTTPError as exc:
            raise WebAccessError("web search request failed") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def _search_bocha(
        self, *, query: str, limit: int
    ) -> list[WebSearchResult]:
        if not self.search_api_key:
            raise WebAccessError(
                "web search backend 'bocha' is not configured: "
                "set FLOWAGENT_WEB_SEARCH_API_KEY"
            )
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds, headers={"User-Agent": self.USER_AGENT}
        )
        try:
            response = await client.post(
                self.search_base_url,
                json={
                    "query": query,
                    "summary": False,
                    "freshness": "noLimit",
                    "count": min(max(limit, 1), 50),
                },
                headers={
                    "Authorization": f"Bearer {self.search_api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise WebAccessError("web search returned an unexpected response")
            code = payload.get("code")
            if code is not None and code != 200:
                raise WebAccessError(
                    "web search failed: "
                    f"{payload.get('msg') or payload.get('message') or code}"
                )
            data = payload.get("data") or {}
            items = (data.get("webPages") or {}).get("value") or []
            results: list[WebSearchResult] = []
            for item in items:
                results.append(
                    WebSearchResult(
                        title=self._clean_text(item.get("name") or ""),
                        url=item.get("url") or "",
                        snippet=self._clean_text(
                            item.get("snippet") or item.get("summary") or ""
                        ),
                    )
                )
                if len(results) >= limit:
                    break
            return results
        except httpx.HTTPError as exc:
            raise WebAccessError("web search request failed") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def open_url(self, *, url: str, max_chars: int = 40_000) -> WebPage:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds, headers={"User-Agent": self.USER_AGENT}
        )
        current_url = url.strip()
        try:
            for _ in range(4):
                await self._require_public_url(current_url)
                response = await self._bounded_get(client, current_url)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise WebAccessError("redirect response is missing a location")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in self.ALLOWED_CONTENT_TYPES:
                    raise WebAccessError(f"unsupported web content type: {content_type or 'unknown'}")
                text, title = self._extract_text(response.content, content_type)
                truncated = len(text) > max_chars
                return WebPage(
                    title=title or urlparse(current_url).hostname or current_url,
                    url=str(response.url),
                    content_type=content_type,
                    text=text[:max_chars],
                    text_truncated=truncated,
                )
            raise WebAccessError("too many redirects")
        except httpx.HTTPStatusError as exc:
            raise WebAccessError(
                f"web page returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise WebAccessError("web page request failed") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def _bounded_get(
        self, client: httpx.AsyncClient, url: str
    ) -> httpx.Response:
        request = client.build_request(
            "GET", url, headers={"User-Agent": self.USER_AGENT}
        )
        response = await client.send(request, stream=True, follow_redirects=False)
        chunks: list[bytes] = []
        size = 0
        try:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self.max_response_bytes:
                    raise WebAccessError("web page exceeded the response size limit")
                chunks.append(chunk)
            decoded_headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() not in {"content-encoding", "content-length"}
            }
            return httpx.Response(
                status_code=response.status_code,
                headers=decoded_headers,
                content=b"".join(chunks),
                request=request,
                extensions=response.extensions,
            )
        finally:
            await response.aclose()

    async def _require_public_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise WebAccessError("only absolute HTTP(S) URLs are allowed")
        if parsed.username or parsed.password:
            raise WebAccessError("URLs containing credentials are not allowed")
        hostname = parsed.hostname.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
            raise WebAccessError("local network URLs are not allowed")
        try:
            literal = ipaddress.ip_address(hostname)
            addresses = [literal]
        except ValueError:
            try:
                resolved = await asyncio.get_running_loop().getaddrinfo(
                    hostname,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            except socket.gaierror as exc:
                raise WebAccessError("web hostname could not be resolved") from exc
            addresses = [ipaddress.ip_address(item[4][0]) for item in resolved]
        if not addresses or any(not address.is_global for address in addresses):
            raise WebAccessError("private or non-public network URLs are not allowed")

    @classmethod
    def _extract_text(cls, content: bytes, content_type: str) -> tuple[str, str]:
        if content_type != "text/html":
            return cls._clean_text(content.decode("utf-8", errors="replace")), ""
        document = html.fromstring(content)
        titles = document.xpath("//title/text()")
        for node in document.xpath("//script|//style|//noscript|//svg"):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
        main_nodes = document.xpath("//main|//article")
        source = main_nodes[0] if main_nodes else document
        return cls._clean_text(source.text_content()), cls._clean_text(
            titles[0] if titles else ""
        )

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _unwrap_search_url(url: str) -> str:
        if url.startswith("//"):
            url = "https:" + url
        parsed = urlparse(url)
        if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            if target:
                return unquote(target)
        return url
