"""Upload -> extract -> chunk -> embed -> upsert."""
from __future__ import annotations

import io
import uuid

from pypdf import PdfReader

from .chunking import chunk_document
from .ports import Embedder, VectorStore


def extract_text(filename: str, data: bytes) -> str:
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    return data.decode("utf-8", errors="replace")


def ingest(
    filename: str,
    data: bytes,
    embedder: Embedder,
    store: VectorStore,
    *,
    target_chars: int = 1200,
    overlap_chars: int = 150,
) -> tuple[str, int]:
    """Returns (document_id, chunk_count). TODO: persist the documents row."""
    document_id = str(uuid.uuid4())
    text = extract_text(filename, data)
    chunks = chunk_document(
        document_id, text, source=filename,
        target_chars=target_chars, overlap_chars=overlap_chars,
    )
    embeddings = embedder.embed_texts([c.content for c in chunks])
    store.upsert(chunks, embeddings)
    return document_id, len(chunks)
