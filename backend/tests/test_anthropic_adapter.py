"""The Claude adapter's two jobs, with a stub client instead of an API key.

Not tested here: whether the prompt produces good answers - that is what
evals/ is for. Tested here: that a response coming back from the SDK is
turned into the app's Answer contract (PLAN.md decision 14) and that
NOT_IN_CONTEXT still becomes a refusal.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.adapters.anthropic_llm import ClaudeAnswerModel
from app.ports import Chunk, RetrievedChunk
from app.rag import REFUSAL

CONTEXT = [
    RetrievedChunk(Chunk("c1", "d1", "Returns within 30 days.", {"source": "policy.pdf"}), 0.9),
    RetrievedChunk(Chunk("c2", "d1", "Refunds are paid weekly.", {"source": "policy.pdf"}), 0.8),
    RetrievedChunk(Chunk("c3", "d2", "Delivery is free.", {"source": "shipping.pdf"}), 0.7),
]


class StubMessages:
    def __init__(self, text: str) -> None:
        self._text = text
        self.kwargs: dict = {}

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)])


def _model(text: str) -> tuple[ClaudeAnswerModel, StubMessages]:
    messages = StubMessages(text)
    return ClaudeAnswerModel(SimpleNamespace(messages=messages)), messages


def test_context_blocks_are_numbered_from_one_with_their_source():
    model, messages = _model("Returns take 30 days [1].")
    model.answer("refund window?", CONTEXT)
    prompt = messages.kwargs["messages"][0]["content"]
    assert "[1] (source: policy.pdf)\nReturns within 30 days." in prompt
    assert "[3] (source: shipping.pdf)\nDelivery is free." in prompt


def test_block_numbers_become_deduplicated_citation_numbers():
    """Blocks 1 and 2 are the same file, so the answer must end up with one chip."""
    model, _ = _model("Returns take 30 days [1] and are paid weekly [2]; delivery is free [3].")
    answer = model.answer("refunds?", CONTEXT)
    assert answer.text == (
        "Returns take 30 days [1] and are paid weekly [1]; delivery is free [2]."
    )
    assert answer.citations == ["policy.pdf", "shipping.pdf"]
    assert answer.grounded is True


def test_not_in_context_becomes_the_refusal():
    model, _ = _model("NOT_IN_CONTEXT")
    answer = model.answer("who won the world cup?", CONTEXT)
    assert answer.text == REFUSAL
    assert answer.citations == []
    assert answer.grounded is False
