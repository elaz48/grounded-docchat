"""Ports (interfaces) that decouple the RAG pipeline from concrete providers.

Runtime wiring: OpenAI embeddings + pgvector + Claude (see adapters/).
Test wiring: placeborag fakes implement the same ports, so the whole
retrieval contract runs offline in CI (see tests/conftest.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Chunk:
    id: str
    document_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    # Normalized convention for the whole app: higher is better, whatever the
    # backend reports natively (pgvector cosine distance is converted).
    score: float


@dataclass(frozen=True)
class Document:
    id: str
    filename: str
    # Derived (COUNT over chunks), not a stored column - see PLAN.md decision 10.
    chunk_count: int


@dataclass(frozen=True)
class Answer:
    text: str
    citations: list[str]
    grounded: bool


class Embedder(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class DocumentStore(Protocol):
    """The document registry, kept separate from the vector index.

    Same Postgres, same adapter object at runtime - but ingest depends on
    both ports explicitly, so the ordering it guarantees (document row
    before chunks, because of the foreign key) is visible in the signature
    rather than buried in an adapter. See PLAN.md decision 9.
    """

    def create_document(self, document_id: str, filename: str) -> None: ...
    def list_documents(self) -> list[Document]: ...


class VectorStore(Protocol):
    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None: ...

    def search(
        self,
        query_text: str,
        query_embedding: list[float],
        k: int = 6,
        where: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]: ...


class AnswerModel(Protocol):
    def answer(self, question: str, context: list[RetrievedChunk]) -> Answer: ...
