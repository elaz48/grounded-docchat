"""A refusal must leave a trace. Today it leaves a 200 and nothing else.

This is the module the last bug report needed. The app answered "I can't
answer that from the uploaded documents", and the log for that request read
in full:

    {"status": 200, "duration_ms": 6853.6, "event": "request",
     "path": "/api/ask", ...}

Two entirely different failures produce that identical line. Retrieval can
come back empty - a corpus gap, a bad filter, an ingest that never ran - and
`RagService.ask` returns REFUSAL without logging (rag.py). Or retrieval can
work perfectly and the prompt guardrail can decide the passages do not
answer the question, and the adapter turns NOT_IN_CONTEXT into the same
REFUSAL, also without logging (adapters/anthropic_llm.py).

The degrade paths already log with `exc_info`, on the stated reasoning that
"a request degraded" without the detail tells you nothing about which
dependency did it (decision 19). The refusal paths are the same argument and
were left out: the user-visible string is identical, so the log is the only
thing that can separate "we have nothing about this" from "we had six
passages and the model would not use them" - which are a corpus problem and
a retrieval-quality problem respectively, and are fixed in different files.

Duration is not a substitute. It separates them only because generation is
slow today, and only for someone who already knows that.
"""
from __future__ import annotations

from types import SimpleNamespace

import structlog
from app.adapters.anthropic_llm import ClaudeAnswerModel
from app.ports import Chunk, RetrievedChunk
from app.rag import REFUSAL, RagService

from tests.conftest import EchoAnswerModel

CONTEXT = [
    RetrievedChunk(Chunk("c1", "d1", "Returns within 30 days.", {"source": "policy.pdf"}), 0.9),
    RetrievedChunk(Chunk("c2", "d2", "Delivery is free.", {"source": "shipping.pdf"}), 0.8),
]


def _claude_returning(text: str) -> ClaudeAnswerModel:
    """The real adapter over a stub client, so the real refusal path runs.

    A hand-rolled double that just returns REFUSAL would make the log test
    below vacuous: it would assert against a double that never logs, and pass
    with the adapter still silent.
    """
    messages = SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)]
        )
    )
    return ClaudeAnswerModel(SimpleNamespace(messages=messages))


def _service(embedder, store, *, min_score=0.0, model=None):
    return RagService(embedder, store, model or EchoAnswerModel(), k=3, min_score=min_score)


def _events(entries: list[dict]) -> list[str]:
    return [entry["event"] for entry in entries]


# --- retrieval came back with nothing to ground on -----------------------


def test_an_empty_retrieval_refusal_is_logged(embedder, store):
    """`store` is the unseeded fixture: nothing to retrieve, so REFUSAL."""
    with structlog.testing.capture_logs() as logs:
        answer = _service(embedder, store).ask("refund policy")

    assert answer.text == REFUSAL
    assert "refused_no_hits" in _events(logs)


def test_the_empty_retrieval_log_says_how_empty_it_was(embedder, store):
    """`retrieved` separates "the store returned nothing" from "the floor ate it".

    Both reach the same `if not hits`, and they are different bugs: the first
    is ingest or the query, the second is the floor being set above hits the
    retriever was asked for - the exact trap decision 18 exists to prevent.
    """
    with structlog.testing.capture_logs() as logs:
        _service(embedder, store).ask("refund policy")

    refusal = next(entry for entry in logs if entry["event"] == "refused_no_hits")
    assert refusal["retrieved"] == 0
    assert refusal["kept"] == 0


def test_hits_dropped_by_the_floor_are_visibly_different_from_no_hits(
    embedder, seeded_store
):
    """A floor above every score is silent today. It must not be.

    min_score=1.0 is unreachable for any RRF score, so retrieval succeeds and
    grounding discards all of it - the failure mode decision 18 could only
    argue about because nothing logged it.
    """
    with structlog.testing.capture_logs() as logs:
        answer = _service(embedder, seeded_store, min_score=1.0).ask("refund policy")

    assert answer.text == REFUSAL
    refusal = next(entry for entry in logs if entry["event"] == "refused_no_hits")
    assert refusal["retrieved"] > 0
    assert refusal["kept"] == 0


# --- the model refused passages it was given -----------------------------


def test_a_not_in_context_refusal_is_logged():
    """The path the bug report actually hit."""
    model = _claude_returning("NOT_IN_CONTEXT")

    with structlog.testing.capture_logs() as logs:
        answer = model.answer("how does it know word order?", CONTEXT)

    assert answer.text == REFUSAL
    assert "refused_not_in_context" in _events(logs)


def test_the_not_in_context_log_names_what_was_in_the_context():
    """Without the sources this line cannot tell you retrieval went wrong.

    The whole diagnosis of the last report was "the fused top 6 contained no
    chunk from the only paper that answers it". That is readable off this
    log line or it is not readable at all without a live database.
    """
    model = _claude_returning("NOT_IN_CONTEXT")

    with structlog.testing.capture_logs() as logs:
        model.answer("how does it know word order?", CONTEXT)

    refusal = next(entry for entry in logs if entry["event"] == "refused_not_in_context")
    assert refusal["hits"] == len(CONTEXT)
    assert refusal["sources"] == ["policy.pdf", "shipping.pdf"]


# --- the two must not be one event ---------------------------------------


def test_the_two_refusals_are_distinguishable_in_the_log(
    embedder, empty_store, seeded_store
):
    """The report in one assertion: same user-visible string, same status.

    If these two ever share an event name, the log is back to being unable to
    answer the only question worth asking about a refusal - which half failed.

    `empty_store`, not `store`: `seeded_store` seeds `store` in place, so
    asking for both here would compare a seeded store against itself.
    """
    with structlog.testing.capture_logs() as empty_logs:
        _service(embedder, empty_store).ask("refund policy")
    with structlog.testing.capture_logs() as guardrail_logs:
        _service(
            embedder, seeded_store, model=_claude_returning("NOT_IN_CONTEXT")
        ).ask("refund policy")

    empty = {e for e in _events(empty_logs) if e.startswith("refused_")}
    guardrail = {e for e in _events(guardrail_logs) if e.startswith("refused_")}
    assert empty and guardrail
    assert empty.isdisjoint(guardrail)


def test_a_grounded_answer_logs_no_refusal(embedder, seeded_store):
    """Guards the cheap wrong fix: logging on every request."""
    with structlog.testing.capture_logs() as logs:
        answer = _service(embedder, seeded_store).ask("refund policy")

    assert answer.grounded is True
    assert [e for e in _events(logs) if e.startswith("refused_")] == []
