"""The degrade path: a failing read path must produce an honest answer, not a 500."""
from app.ports import Answer, RetrievedChunk
from app.rag import DEGRADED_GENERATION, DEGRADED_RETRIEVAL, REFUSAL, RagService
from placeborag import RetrievalTimeout

from tests.conftest import EchoAnswerModel


class ExplodingAnswerModel:
    """AnswerModel stub that fails the way a rate-limited or overloaded LLM does."""

    def answer(self, question: str, context: list[RetrievedChunk]) -> Answer:
        raise RuntimeError("overloaded_error: upstream 529")


def _service(embedder, store, min_score=0.0, model=None):
    return RagService(embedder, store, model or EchoAnswerModel(), k=3, min_score=min_score)


def test_retrieval_timeout_degrades_gracefully(embedder, seeded_store):
    seeded_store.fake.fail_next_query(RetrievalTimeout("slow"))
    answer = _service(embedder, seeded_store).ask("refund policy")
    assert answer.text == DEGRADED_RETRIEVAL
    assert answer.grounded is False


def test_generation_failure_degrades_gracefully(embedder, seeded_store):
    """Retrieval succeeded, the model call did not: still an answer, not a 500.

    Distinct text from the retrieval failure, because the two are different
    events for anyone reading the logs or the screen - and no citations: an
    answer we never produced cannot cite anything.
    """
    service = _service(embedder, seeded_store, model=ExplodingAnswerModel())
    answer = service.ask("refund policy")
    assert answer.text == DEGRADED_GENERATION
    assert answer.grounded is False
    assert answer.citations == []


def test_empty_results_refuse_instead_of_hallucinating(embedder, store):
    answer = _service(embedder, store).ask("refund policy")
    assert answer.text == REFUSAL
    assert answer.grounded is False


def test_grounded_answer_carries_citations(embedder, seeded_store):
    answer = _service(embedder, seeded_store).ask("refund policy")
    assert answer.grounded is True
    assert "policy.pdf" in answer.citations
