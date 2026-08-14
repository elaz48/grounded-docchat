"""placeborag fakes wired to the app's ports.

This is the point of the test architecture: the retrieval contract
(ranking, grounding, degradation) runs offline, deterministically, with no
API keys - in CI and on any machine. placeborag is my own OSS library:
https://github.com/elaz48/placeborag
"""
from __future__ import annotations

from typing import Any

import pytest
from app.ports import Answer, Chunk, RetrievedChunk
from placeborag import FakeEmbedder, FakeVectorStore

CLUSTERS = {
    "refund": ["refund policy", "money back", "returns within 30 days"],
    "shipping": ["delivery times", "shipping costs"],
}


class PlaceboEmbedderAdapter:
    """placeborag FakeEmbedder behind the app's Embedder port."""

    def __init__(self, fake: FakeEmbedder) -> None:
        self.fake = fake

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.fake.embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.fake.embed(text)


class PlaceboStoreAdapter:
    """placeborag FakeVectorStore behind the app's VectorStore port.

    Uses the qdrant profile: similarity scores, higher is better - the same
    convention ports.py declares app-wide, so no conversion is needed here.
    """

    def __init__(self, fake: FakeVectorStore) -> None:
        self.fake = fake
        self._chunks: dict[str, Chunk] = {}

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        for chunk in chunks:
            # document_id is filterable in `where` because Postgres has it as
            # a column; the fake only knows metadata, so index it there too.
            # Returned chunks come from self._chunks, so this stays internal.
            self.fake.upsert(
                chunk.id,
                chunk.content,
                metadata={**chunk.metadata, "document_id": chunk.document_id},
            )
            self._chunks[chunk.id] = chunk

    def search(
        self, query_text: str, query_embedding: list[float],
        k: int = 6, where: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        matches = self.fake.query(query_text, k=k, where=where)
        return [
            RetrievedChunk(chunk=self._chunks[m.id], score=float(m.score))
            for m in matches
        ]


class EchoAnswerModel:
    """Deterministic AnswerModel double: proves the service passed grounded context."""

    def answer(self, question: str, context: list[RetrievedChunk]) -> Answer:
        sources = [c.chunk.metadata.get("source", "unknown") for c in context]
        return Answer(text=f"echo:{question}", citations=sources, grounded=True)


@pytest.fixture
def embedder() -> PlaceboEmbedderAdapter:
    return PlaceboEmbedderAdapter(FakeEmbedder(clusters=CLUSTERS, cluster_match="substring"))


@pytest.fixture
def store(embedder: PlaceboEmbedderAdapter) -> PlaceboStoreAdapter:
    fake = FakeVectorStore(embedder=embedder.fake, profile="qdrant", filter_mode="pre")
    return PlaceboStoreAdapter(fake)


SEED_CHUNKS = [
    Chunk("c1", "d1", "Our refund policy allows returns within 30 days.",
          {"source": "policy.pdf", "chunk_index": 0}),
    Chunk("c2", "d1", "Refunds: how to get your money back after a purchase.",
          {"source": "policy.pdf", "chunk_index": 1}),
    Chunk("c3", "d2", "Delivery times and shipping costs for remote islands.",
          {"source": "shipping.pdf", "chunk_index": 0}),
]


def _seed(adapter: PlaceboStoreAdapter) -> PlaceboStoreAdapter:
    # embeddings unused by the fake; its geometry comes from the clusters
    adapter.upsert(SEED_CHUNKS, embeddings=[[0.0]] * len(SEED_CHUNKS))
    return adapter


@pytest.fixture
def seeded_store(store: PlaceboStoreAdapter) -> PlaceboStoreAdapter:
    return _seed(store)


@pytest.fixture
def post_filter_store(embedder: PlaceboEmbedderAdapter) -> PlaceboStoreAdapter:
    """Same data, but filtering happens *after* the top-k cut.

    Stands in for the retrieval backend we deliberately did not build: it is
    the control case in test_retrieval_contract.py that shows what
    post-filtering costs (PLAN.md decision 13).
    """
    fake = FakeVectorStore(embedder=embedder.fake, profile="qdrant", filter_mode="post")
    return _seed(PlaceboStoreAdapter(fake))
