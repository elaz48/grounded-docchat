"""OpenAI text-embedding-3-small behind the Embedder port.

Chosen for cost + ubiquity (PLAN.md decision log). Swapping the model means
changing db/init.sql vector dimension and reindexing - which is exactly the
code path the placeborag-based tests keep honest.
"""
from __future__ import annotations

from openai import OpenAI

MODEL = "text-embedding-3-small"


class OpenAIEmbedder:
    def __init__(self, api_key: str) -> None:
        self._client = OpenAI(api_key=api_key)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=MODEL, input=texts)
        return [item.embedding for item in response.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]
