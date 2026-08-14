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
class Answer:
    text: str
    citations: list[str]
    grounded: bool


class Embedder(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


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
