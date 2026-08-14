"""Parameter-adaptation contract for the Postgres adapter, without a Postgres.

These tests do not check that the SQL is *correct* - that needs a real
database and a human reading the query (CLAUDE.md: SQL is review-required).
They check the part that silently rots: psycopg needs a `dict` wrapped in
Json() before it will bind to JSONB, and a `list[float]` wrapped in Vector()
before it will bind to a pgvector column. Both fail only at runtime against
a live DB, which is exactly the feedback loop this suite exists to shorten.
"""
from __future__ import annotations

from contextlib import contextmanager

from app.adapters.pgvector_store import PgVectorStore
from app.ports import Chunk
from pgvector import Vector
from psycopg.types.json import Json


class FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self.calls: list[tuple[str, object]] = []
        self._rows = rows

    def execute(self, sql: str, params: object = None) -> None:
        self.calls.append((sql, params))

    def fetchall(self) -> list[tuple]:
        return self._rows

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class FakePool:
    def __init__(self, rows: list[tuple] | None = None) -> None:
        self.cursor = FakeCursor(rows or [])

    @contextmanager
    def connection(self):
        yield FakeConnection(self.cursor)


def _store(rows: list[tuple] | None = None) -> tuple[PgVectorStore, FakePool]:
    pool = FakePool(rows)
    return PgVectorStore(pool), pool


CHUNK = Chunk(
    id="c1",
    document_id="d1",
    content="Refunds within 30 days.",
    metadata={"source": "policy.pdf", "chunk_index": 2},
)


def test_metadata_is_wrapped_for_jsonb():
    store, pool = _store()
    store.upsert([CHUNK], [[0.5, 0.25]])
    _, params = pool.cursor.calls[0]
    metadata = params[4]
    assert isinstance(metadata, Json)
    assert metadata.obj == CHUNK.metadata


def test_embedding_is_wrapped_for_pgvector():
    store, pool = _store()
    store.upsert([CHUNK], [[0.5, 0.25]])
    _, params = pool.cursor.calls[0]
    assert isinstance(params[5], Vector)
    assert params[5].to_text() == "[0.5,0.25]"


def test_chunk_index_comes_from_metadata():
    store, pool = _store()
    store.upsert([CHUNK], [[0.5, 0.25]])
    _, params = pool.cursor.calls[0]
    assert params[:3] == ("c1", "d1", 2)


def test_create_document_binds_id_and_filename():
    store, pool = _store()
    store.create_document("d1", "policy.pdf")
    sql, params = pool.cursor.calls[0]
    assert "INSERT INTO documents" in sql
    assert params == ("d1", "policy.pdf")


def test_list_documents_maps_rows_to_the_port_type():
    store, _ = _store(rows=[("d1", "policy.pdf", 3), ("d2", "shipping.pdf", 0)])
    documents = store.list_documents()
    assert [(d.id, d.filename, d.chunk_count) for d in documents] == [
        ("d1", "policy.pdf", 3),
        ("d2", "shipping.pdf", 0),
    ]


def test_search_reports_higher_is_better_scores():
    """ports.py declares the app-wide convention; the adapter must honour it."""
    store, _ = _store(
        rows=[
            ("c1", "d1", "Refunds within 30 days.", {"source": "policy.pdf"}, 0.031),
            ("c2", "d1", "Shipping is extra.", {"source": "policy.pdf"}, 0.016),
        ]
    )
    hits = store.search("refund", [0.1, 0.2], k=2)
    assert [h.score for h in hits] == sorted([h.score for h in hits], reverse=True)
    assert hits[0].chunk.content == "Refunds within 30 days."


def test_search_wraps_the_query_vector_too():
    store, pool = _store()
    store.search("refund", [0.1, 0.2], k=2)
    _, params = pool.cursor.calls[0]
    assert isinstance(params["qvec"], Vector)
