"""Claude behind the AnswerModel port: grounded answers with [n] citations."""
from __future__ import annotations

from anthropic import Anthropic

from ..citations import normalize_citations
from ..ports import Answer, RetrievedChunk

MODEL = "claude-sonnet-4-6"

SYSTEM = """You answer questions strictly from the provided context blocks.
Rules:
- Use ONLY the numbered context blocks below. No outside knowledge.
- Cite every claim with the block number in square brackets, e.g. [2].
- If the context does not contain the answer, say exactly: NOT_IN_CONTEXT
- Be concise and factual."""


class ClaudeAnswerModel:
    def __init__(self, client: Anthropic) -> None:
        self._client = client

    @classmethod
    def from_api_key(cls, api_key: str) -> ClaudeAnswerModel:
        return cls(Anthropic(api_key=api_key))

    def answer(self, question: str, context: list[RetrievedChunk]) -> Answer:
        sources = [hit.chunk.metadata.get("source", "unknown") for hit in context]
        blocks = "\n\n".join(
            f"[{i + 1}] (source: {source})\n{hit.chunk.content}"
            for i, (hit, source) in enumerate(zip(context, sources, strict=True))
        )
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=SYSTEM,
            messages=[{"role": "user", "content": f"Context:\n{blocks}\n\nQuestion: {question}"}],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()

        if "NOT_IN_CONTEXT" in text:
            from ..rag import REFUSAL
            return Answer(text=REFUSAL, citations=[], grounded=False)

        # The model cites block numbers; the UI shows citation numbers.
        # citations.py is the one place that translates between them.
        cited = normalize_citations(text, sources)
        return Answer(text=cited.text, citations=cited.citations, grounded=True)
