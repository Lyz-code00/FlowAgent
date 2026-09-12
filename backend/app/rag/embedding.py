import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx


class EmbeddingProvider(ABC):
    model_name: str
    dimensions: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        pass


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model
        self.dimensions = dimensions
        self._client = client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("embedding input cannot be empty")
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=45)
        try:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model_name,
                    "input": texts,
                    "encoding_format": "float",
                    "dimensions": self.dimensions,
                },
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        finally:
            if owns_client:
                await client.aclose()
        ordered = sorted(data.get("data") or [], key=lambda item: item.get("index", 0))
        vectors = [item.get("embedding") for item in ordered]
        if len(vectors) != len(texts) or any(
            not isinstance(vector, list) or len(vector) != self.dimensions
            for vector in vectors
        ):
            raise RuntimeError("embedding response has an unexpected shape")
        return [[float(value) for value in vector] for vector in vectors]


class DevelopmentHashEmbeddingProvider(EmbeddingProvider):
    """Deterministic local semantic-lite embedding for tests and setup."""

    model_name = "development-hash-embedding"

    def __init__(self, *, dimensions: int = 1536) -> None:
        if dimensions < 8:
            raise ValueError("embedding dimensions must be at least 8")
        self.dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        tokens = _tokens(text)
        vector = [0.0] * self.dimensions
        for token in tokens:
            digest = hashlib.blake2b(token.encode(), digest_size=16).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimensions
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def _tokens(text: str) -> list[str]:
    lowered = text.lower()
    words = re.findall(r"[a-z0-9_]+", lowered)
    chinese = re.findall(r"[\u4e00-\u9fff]", lowered)
    bigrams = ["".join(chinese[index : index + 2]) for index in range(len(chinese) - 1)]
    return words + chinese + bigrams or [lowered]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return -1.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)
