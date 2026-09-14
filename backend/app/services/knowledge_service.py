import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    DocumentChunk,
    KnowledgeBase,
    KnowledgeDocument,
    Tenant,
)
from app.rag.chunker import chunk_sections
from app.rag.embedding import EmbeddingProvider, cosine_similarity
from app.rag.parser import DocumentParseError, parse_document


@dataclass(frozen=True)
class DocumentInfo:
    id: int
    title: str
    source_name: str
    status: str
    chunk_count: int
    source_url: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class SearchHit:
    citation_id: int
    document_id: int
    title: str
    source_name: str
    source_locator: str
    content: str
    score: float
    source_url: str | None = None
    dense_score: float = 0
    lexical_score: float = 0


class KnowledgeService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_provider: EmbeddingProvider,
        *,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
        max_file_bytes: int = 10 * 1024 * 1024,
        min_score: float = 0.05,
    ) -> None:
        self.session_factory = session_factory
        self.embedding_provider = embedding_provider
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_file_bytes = max_file_bytes
        self.min_score = min_score

    async def ingest(
        self,
        *,
        tenant_key: str,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        title: str | None = None,
        source_url: str | None = None,
    ) -> DocumentInfo:
        if not data:
            raise DocumentParseError("document is empty")
        if len(data) > self.max_file_bytes:
            raise DocumentParseError("document exceeds the configured size limit")
        safe_name = Path(filename).name
        document_id = await self._create_processing_document(
            tenant_key=tenant_key,
            title=(title or Path(safe_name).stem).strip() or safe_name,
            source_name=safe_name,
            content_type=content_type,
            source_url=source_url,
        )
        try:
            sections = parse_document(safe_name, data)
            chunks = chunk_sections(
                sections,
                chunk_size=self.chunk_size,
                overlap=self.chunk_overlap,
            )
            if not chunks:
                raise DocumentParseError("document does not contain indexable text")
            embeddings: list[list[float]] = []
            for start in range(0, len(chunks), 128):
                embeddings.extend(
                    await self.embedding_provider.embed(
                        [item.content for item in chunks[start : start + 128]]
                    )
                )
            if len(embeddings) != len(chunks):
                raise RuntimeError("embedding provider returned the wrong vector count")
            async with self.session_factory() as session:
                document = await session.get(KnowledgeDocument, document_id)
                if document is None:
                    raise RuntimeError("knowledge document disappeared during indexing")
                session.add_all(
                    [
                        DocumentChunk(
                            document_id=document_id,
                            chunk_index=chunk.index,
                            content=chunk.content,
                            embedding=embedding,
                            source_locator=chunk.locator,
                            chunk_metadata={"source_name": safe_name},
                        )
                        for chunk, embedding in zip(chunks, embeddings)
                    ]
                )
                document.status = "ready"
                document.chunk_count = len(chunks)
                document.error = None
                await session.commit()
                return self._document_info(document)
        except Exception as exc:
            async with self.session_factory() as session:
                document = await session.get(KnowledgeDocument, document_id)
                if document is not None:
                    document.status = "failed"
                    document.error = str(exc)[:1000]
                    await session.commit()
            raise

    async def search(
        self, *, tenant_id: int, query: str, top_k: int
    ) -> list[SearchHit]:
        query_vector = (await self.embedding_provider.embed([query]))[0]
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(DocumentChunk, KnowledgeDocument)
                    .join(
                        KnowledgeDocument,
                        KnowledgeDocument.id == DocumentChunk.document_id,
                    )
                    .join(
                        KnowledgeBase,
                        KnowledgeBase.id == KnowledgeDocument.knowledge_base_id,
                    )
                    .where(
                        KnowledgeBase.tenant_id == tenant_id,
                        KnowledgeDocument.status == "ready",
                    )
                    .limit(5000)
                )
            ).all()
        dense_scores = [
            cosine_similarity(query_vector, chunk.embedding) for chunk, _ in rows
        ]
        lexical_scores = self._bm25_scores(query, [chunk.content for chunk, _ in rows])
        max_lexical = max(lexical_scores, default=0)
        scored = []
        for index, (chunk, document) in enumerate(rows):
            dense = dense_scores[index]
            lexical = lexical_scores[index]
            normalized_dense = max(0.0, min(1.0, (dense + 1) / 2))
            normalized_lexical = lexical / max_lexical if max_lexical > 0 else 0
            hybrid = 0.65 * normalized_dense + 0.35 * normalized_lexical
            scored.append((hybrid, dense, lexical, chunk, document))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected = [
            item for item in scored if item[1] >= self.min_score or item[2] > 0
        ][:top_k]
        return [
            SearchHit(
                citation_id=index,
                document_id=document.id,
                title=document.title,
                source_name=document.source_name,
                source_url=document.source_url,
                source_locator=chunk.source_locator,
                content=chunk.content,
                score=round(score, 6),
                dense_score=round(dense, 6),
                lexical_score=round(lexical, 6),
            )
            for index, (score, dense, lexical, chunk, document) in enumerate(selected, 1)
        ]

    @classmethod
    def _bm25_scores(cls, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        query_terms = cls._tokenize(query)
        tokenized = [cls._tokenize(document) for document in documents]
        if not query_terms:
            return [0.0] * len(documents)
        average_length = sum(len(tokens) for tokens in tokenized) / max(1, len(tokenized))
        document_frequency = Counter(
            term for tokens in tokenized for term in set(tokens)
        )
        k1 = 1.5
        b = 0.75
        scores: list[float] = []
        for tokens in tokenized:
            frequencies = Counter(tokens)
            length_ratio = len(tokens) / average_length if average_length else 0
            score = 0.0
            for term in query_terms:
                frequency = frequencies[term]
                if not frequency:
                    continue
                frequency_in_documents = document_frequency[term]
                inverse_frequency = math.log(
                    1
                    + (len(documents) - frequency_in_documents + 0.5)
                    / (frequency_in_documents + 0.5)
                )
                score += inverse_frequency * (
                    frequency * (k1 + 1)
                    / (frequency + k1 * (1 - b + b * length_ratio))
                )
            scores.append(score)
        return scores

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        tokens: list[str] = []
        for segment in re.findall(r"[a-z0-9_.:/#-]+|[\u4e00-\u9fff]+", text.lower()):
            if re.fullmatch(r"[\u4e00-\u9fff]+", segment):
                tokens.extend(segment[index : index + 2] for index in range(len(segment) - 1))
                if len(segment) == 1:
                    tokens.append(segment)
            else:
                tokens.append(segment)
        return tokens

    async def list_documents(self, *, tenant_key: str) -> list[DocumentInfo]:
        async with self.session_factory() as session:
            documents = (
                await session.scalars(
                    select(KnowledgeDocument)
                    .join(
                        KnowledgeBase,
                        KnowledgeBase.id == KnowledgeDocument.knowledge_base_id,
                    )
                    .join(Tenant, Tenant.id == KnowledgeBase.tenant_id)
                    .where(Tenant.external_key == tenant_key)
                    .order_by(KnowledgeDocument.id.desc())
                )
            ).all()
            return [self._document_info(item) for item in documents]

    async def delete_document(self, *, tenant_key: str, document_id: int) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                delete(KnowledgeDocument).where(
                    KnowledgeDocument.id == document_id,
                    KnowledgeDocument.knowledge_base_id.in_(
                        select(KnowledgeBase.id)
                        .join(Tenant, Tenant.id == KnowledgeBase.tenant_id)
                        .where(Tenant.external_key == tenant_key)
                    ),
                )
            )
            await session.commit()
            return bool(result.rowcount)

    async def ingest_for_tenant_id(
        self,
        *,
        tenant_id: int,
        filename: str,
        data: bytes,
        content_type: str = "text/plain",
        title: str | None = None,
        source_url: str | None = None,
    ) -> DocumentInfo:
        async with self.session_factory() as session:
            tenant_key = await session.scalar(
                select(Tenant.external_key).where(Tenant.id == tenant_id)
            )
        if tenant_key is None:
            raise ValueError("tenant not found")
        return await self.ingest(
            tenant_key=tenant_key,
            filename=filename,
            data=data,
            content_type=content_type,
            title=title,
            source_url=source_url,
        )

    async def replace_source_versions(
        self, *, tenant_id: int, source_url: str, keep_document_id: int
    ) -> int:
        """Delete older copies of a successfully re-imported source document."""
        async with self.session_factory() as session:
            result = await session.execute(
                delete(KnowledgeDocument).where(
                    KnowledgeDocument.source_url == source_url,
                    KnowledgeDocument.id != keep_document_id,
                    KnowledgeDocument.knowledge_base_id.in_(
                        select(KnowledgeBase.id).where(
                            KnowledgeBase.tenant_id == tenant_id
                        )
                    ),
                )
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def _create_processing_document(
        self,
        *,
        tenant_key: str,
        title: str,
        source_name: str,
        content_type: str,
        source_url: str | None,
    ) -> int:
        async with self.session_factory() as session:
            tenant = await session.scalar(
                select(Tenant).where(Tenant.external_key == tenant_key)
            )
            if tenant is None:
                tenant = Tenant(
                    external_key=tenant_key, name=f"Tenant {tenant_key}", status="active"
                )
                session.add(tenant)
                await session.flush()
            knowledge_base = await session.scalar(
                select(KnowledgeBase).where(
                    KnowledgeBase.tenant_id == tenant.id,
                    KnowledgeBase.name == "default",
                )
            )
            if knowledge_base is None:
                knowledge_base = KnowledgeBase(
                    tenant_id=tenant.id,
                    name="default",
                    embedding_model=self.embedding_provider.model_name,
                )
                session.add(knowledge_base)
                await session.flush()
            elif knowledge_base.embedding_model != self.embedding_provider.model_name:
                raise RuntimeError(
                    "knowledge base embedding model differs from current configuration"
                )
            document = KnowledgeDocument(
                knowledge_base_id=knowledge_base.id,
                title=title,
                source_name=source_name,
                source_url=source_url,
                content_type=content_type,
                status="processing",
                chunk_count=0,
            )
            session.add(document)
            await session.commit()
            return document.id

    @staticmethod
    def _document_info(document: KnowledgeDocument) -> DocumentInfo:
        return DocumentInfo(
            id=document.id,
            title=document.title,
            source_name=document.source_name,
            source_url=document.source_url,
            status=document.status,
            chunk_count=document.chunk_count,
            error=document.error,
        )
