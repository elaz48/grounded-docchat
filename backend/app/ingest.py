"""Upload -> extract -> chunk -> embed -> persist."""
from __future__ import annotations

import io
import uuid

import structlog
from pypdf import PdfReader

from .chunking import chunk_document
from .ports import DocumentStore, Embedder, VectorStore

log = structlog.get_logger()


class EmptyDocumentError(ValueError):
    """No extractable text - a scanned PDF, or an empty file.

    Raised before anything is written so a dead document never reaches the
    index; main.py turns it into a 400 the upload UI can explain.
    """


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
    documents: DocumentStore,
    *,
    target_chars: int = 1200,
    overlap_chars: int = 150,
) -> tuple[str, int]:
    """Returns (document_id, chunk_count). Raises EmptyDocumentError if the
    file yields no text."""
    document_id = str(uuid.uuid4())
    text = extract_text(filename, data)
    chunks = chunk_document(
        document_id, text, source=filename,
        target_chars=target_chars, overlap_chars=overlap_chars,
    )
    if not chunks:
        hint = (
            " It may be a scanned PDF; those need OCR before upload."
            if filename.lower().endswith(".pdf")
            else ""
        )
        raise EmptyDocumentError(f"No text could be extracted from {filename}.{hint}")

    embeddings = embedder.embed_texts([c.content for c in chunks])
    # Order matters: chunks.document_id is a foreign key (db/init.sql).
    documents.create_document(document_id, filename)
    store.upsert(chunks, embeddings)
    log.info("document_ingested", document_id=document_id, filename=filename,
             chunks=len(chunks))
    return document_id, len(chunks)
