"""Claude behind the AnswerModel port: grounded answers with [n] citations."""
from __future__ import annotations

import re

from anthropic import Anthropic

from ..ports import Answer, RetrievedChunk

MODEL = "claude-sonnet-4-6"

SYSTEM = """You answer questions strictly from the provided context blocks.
Rules:
- Use ONLY the numbered context blocks below. No outside knowledge.
- Cite every claim with the block number in square brackets, e.g. [2].
- If the context does not contain the answer, say exactly: NOT_IN_CONTEXT
- Be concise and factual."""


class ClaudeAnswerModel:
    def __init__(self, api_key: str) -> None:
        self._client = Anthropic(api_key=api_key)

    def answer(self, question: str, context: list[RetrievedChunk]) -> Answer:
        blocks = "\n\n".join(
            f"[{i + 1}] (source: {hit.chunk.metadata.get('source', 'unknown')})\n"
            f"{hit.chunk.content}"
            for i, hit in enumerate(context)
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

        cited = sorted({int(m) for m in re.findall(r"\[(\d+)\]", text)})
        citations = [
            context[i - 1].chunk.metadata.get("source", "unknown")
            for i in cited
            if 0 < i <= len(context)
        ]
        return Answer(text=text, citations=citations, grounded=True)
