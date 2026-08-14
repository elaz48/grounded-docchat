"""Retrieval + answer assembly with a grounding guardrail.

The service depends only on ports, which is what makes it testable offline
with placeborag (tests/test_failure_paths.py exercises the degrade path).
"""
from __future__ import annotations

import structlog

from .ports import Answer, AnswerModel, Embedder, RetrievedChunk, VectorStore

log = structlog.get_logger()

REFUSAL = (
    "I can't answer that from the uploaded documents. "
    "Try rephrasing, or upload a document that covers this topic."
)
DEGRADED = (
    "Retrieval is temporarily unavailable, so I can't answer right now. "
    "Please try again in a moment."
)


class RagService:
    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        model: AnswerModel,
        *,
        k: int = 6,
        min_score: float = 0.0,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._model = model
        self._k = k
        self._min_score = min_score

    def ask(self, question: str) -> Answer:
        try:
            query_embedding = self._embedder.embed_query(question)
            hits = self._store.search(question, query_embedding, k=self._k)
        except Exception:
            # Degrade, don't collapse: a read-path failure becomes an honest
            # "try again" instead of a 500. Covered by test_failure_paths.py.
            log.warning("retrieval_failed", question_len=len(question))
            return Answer(text=DEGRADED, citations=[], grounded=False)

        hits = self._grounded_hits(hits)
        if not hits:
            return Answer(text=REFUSAL, citations=[], grounded=False)

        return self._model.answer(question, hits)

    def _grounded_hits(self, hits: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return [h for h in hits if h.score >= self._min_score]
