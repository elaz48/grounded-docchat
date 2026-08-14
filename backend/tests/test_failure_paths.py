"""The degrade path: a failing read path must produce an honest answer, not a 500."""
from app.rag import DEGRADED, REFUSAL, RagService
from placeborag import RetrievalTimeout

from tests.conftest import EchoAnswerModel


def _service(embedder, store, min_score=0.0):
    return RagService(embedder, store, EchoAnswerModel(), k=3, min_score=min_score)


def test_retrieval_timeout_degrades_gracefully(embedder, seeded_store):
    seeded_store.fake.fail_next_query(RetrievalTimeout("slow"))
    answer = _service(embedder, seeded_store).ask("refund policy")
    assert answer.text == DEGRADED
    assert answer.grounded is False


def test_empty_results_refuse_instead_of_hallucinating(embedder, store):
    answer = _service(embedder, store).ask("refund policy")
    assert answer.text == REFUSAL
    assert answer.grounded is False


def test_grounded_answer_carries_citations(embedder, seeded_store):
    answer = _service(embedder, seeded_store).ask("refund policy")
    assert answer.grounded is True
    assert "policy.pdf" in answer.citations
