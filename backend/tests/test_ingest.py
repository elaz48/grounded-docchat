"""M1: what upload must do before anyone can ask a question.

Two things here are contracts, not implementation details:
  1. the documents row is written *before* the chunks, because
     chunks.document_id is a foreign key (db/init.sql);
  2. a file with no extractable text is rejected loudly - a scanned PDF
     with no text layer is the most common real upload failure, and
     silently registering an empty document would make /api/ask refuse
     later with no explanation.
"""
from __future__ import annotations

import pytest
from app.ingest import EmptyDocumentError, extract_text, ingest
from app.ports import Chunk, Document
from app.rag import RagService

from tests.conftest import EchoAnswerModel


def minimal_pdf(text: str) -> bytes:
    """Smallest valid one-page PDF carrying a single text run."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


class RecordingDocumentStore:
    """DocumentStore double that remembers call order (see module docstring)."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.rows: list[Document] = []

    def create_document(self, document_id: str, filename: str) -> None:
        self.calls.append("create_document")
        self.rows.append(Document(id=document_id, filename=filename, chunk_count=0))

    def list_documents(self) -> list[Document]:
        return list(self.rows)


class RecordingVectorStore:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.chunks: list[Chunk] = []
        self.embeddings: list[list[float]] = []

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        self.calls.append("upsert")
        self.chunks.extend(chunks)
        self.embeddings.extend(embeddings)

    def search(self, query_text, query_embedding, k=6, where=None):  # pragma: no cover
        raise AssertionError("ingest must not search")


class CountingEmbedder:
    """Deterministic Embedder double; also proves we never embed an empty batch."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        assert texts, "embedding an empty batch is a wasted API call"
        self.batches.append(texts)
        return [[float(len(t))] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text))]


@pytest.fixture
def wiring():
    calls: list[str] = []
    return calls, RecordingDocumentStore(calls), RecordingVectorStore(calls), CountingEmbedder()


TEXT = "Refund policy.\n\nReturns are accepted within 30 days of delivery.\n\nShipping is extra."


def test_document_row_is_written_before_its_chunks(wiring):
    calls, documents, store, embedder = wiring
    ingest("policy.txt", TEXT.encode(), embedder, store, documents)
    assert calls.index("create_document") < calls.index("upsert")


def test_ingest_returns_document_id_and_chunk_count(wiring):
    _, documents, store, embedder = wiring
    document_id, chunk_count = ingest(
        "policy.txt", TEXT.encode(), embedder, store, documents, target_chars=60, overlap_chars=10
    )
    assert chunk_count == len(store.chunks) > 1
    assert documents.rows[0].id == document_id


def test_persisted_row_carries_the_uploaded_filename(wiring):
    _, documents, store, embedder = wiring
    ingest("Q3 report.txt", TEXT.encode(), embedder, store, documents)
    assert documents.rows[0].filename == "Q3 report.txt"


def test_every_chunk_belongs_to_the_new_document(wiring):
    _, documents, store, embedder = wiring
    document_id, _ = ingest(
        "policy.txt", TEXT.encode(), embedder, store, documents, target_chars=60, overlap_chars=10
    )
    assert {c.document_id for c in store.chunks} == {document_id}
    assert {c.metadata["source"] for c in store.chunks} == {"policy.txt"}


def test_chunks_and_embeddings_stay_aligned(wiring):
    _, documents, store, embedder = wiring
    ingest(
        "policy.txt", TEXT.encode(), embedder, store, documents, target_chars=60, overlap_chars=10
    )
    assert len(store.embeddings) == len(store.chunks)
    assert embedder.batches == [[c.content for c in store.chunks]]


def test_two_uploads_of_the_same_file_are_separate_documents(wiring):
    _, documents, store, embedder = wiring
    first, _ = ingest("policy.txt", TEXT.encode(), embedder, store, documents)
    second, _ = ingest("policy.txt", TEXT.encode(), embedder, store, documents)
    assert first != second


def test_pdf_text_is_extracted():
    assert "Refund policy" in extract_text("policy.pdf", minimal_pdf("Refund policy: 30 days."))


def test_plain_text_falls_back_to_replacement_chars():
    assert extract_text("notes.txt", b"caf\xe9") == "caf�"


def test_document_without_text_is_rejected_before_anything_is_written(wiring):
    calls, documents, store, embedder = wiring
    with pytest.raises(EmptyDocumentError):
        ingest("scan.pdf", minimal_pdf(" "), embedder, store, documents)
    assert calls == []
    assert documents.rows == []


def test_empty_pdf_suggests_ocr_but_an_empty_text_file_does_not(wiring):
    """The message reaches the upload UI verbatim; it should fit the file."""
    _, documents, store, embedder = wiring
    with pytest.raises(EmptyDocumentError, match="OCR"):
        ingest("scan.pdf", minimal_pdf(" "), embedder, store, documents)
    with pytest.raises(EmptyDocumentError) as empty_text:
        ingest("notes.txt", b"   \n\n  ", embedder, store, documents)
    assert "OCR" not in str(empty_text.value)


def test_uploaded_document_is_answerable_end_to_end(embedder, store):
    """Upload -> retrieve -> answer, offline: the whole M1 path, from PDF bytes."""
    documents = RecordingDocumentStore([])
    pdf = minimal_pdf("Our refund policy allows returns within 30 days.")
    ingest("policy.pdf", pdf, embedder, store, documents)
    answer = RagService(embedder, store, EchoAnswerModel(), k=3, min_score=0.0).ask(
        "refund policy"
    )
    assert answer.grounded is True
    assert answer.citations == ["policy.pdf"]
