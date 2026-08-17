"""Retrieval + answer assembly with a grounding guardrail.

The service depends only on ports, which is what makes it testable offline:
placeborag fakes stand in for the embedder and the store, small stubs for the
model (tests/test_failure_paths.py exercises both degrade paths).
"""
from __future__ import annotations

import structlog

from .ports import Answer, AnswerModel, Embedder, RetrievedChunk, VectorStore

log = structlog.get_logger()

REFUSAL = (
    "I can't answer that from the uploaded documents. "
    "Try rephrasing, or upload a document that covers this topic."
)
# Two degrade messages, not one: the two failures are different events for
# whoever reads them, and collapsing them would hide which half broke.
DEGRADED_RETRIEVAL = (
    "Retrieval is temporarily unavailable, so I can't answer right now. "
    "Please try again in a moment."
)
DEGRADED_GENERATION = (
    "I found relevant passages but couldn't generate an answer just now. "
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
        except Exception as exc:
            # Degrade, don't collapse: a read-path failure becomes an honest
            # "try again" instead of a 500. Covered by test_failure_paths.py.
            # exc_info carries the traceback: the message alone tells you a
            # request degraded but not which dependency did it.
            log.warning(
                "retrieval_failed",
                error=type(exc).__name__,
                question_len=len(question),
                exc_info=True,
            )
            return Answer(text=DEGRADED_RETRIEVAL, citations=[], grounded=False)

        hits = self._grounded_hits(hits)
        if not hits:
            return Answer(text=REFUSAL, citations=[], grounded=False)

        try:
            return self._model.answer(question, hits)
        except Exception as exc:
            # The generation path degrades the same way: rate limits, overload
            # and timeouts are the LLM's normal failure modes, and a 500 would
            # tell the user nothing they can act on.
            log.warning(
                "generation_failed",
                error=type(exc).__name__,
                question_len=len(question),
                hits=len(hits),
                exc_info=True,
            )
            return Answer(text=DEGRADED_GENERATION, citations=[], grounded=False)

    def _grounded_hits(self, hits: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return [h for h in hits if h.score >= self._min_score]
