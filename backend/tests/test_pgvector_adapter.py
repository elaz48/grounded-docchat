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


# --- `where` -> SQL predicates (M2) -------------------------------------
#
# The point of these is structural: the predicates must sit *inside* the vec
# and kw CTEs, above their LIMIT, so filtering happens before the top-k cut.
# Filtering after the cut silently under-returns - see
# test_retrieval_contract.py for that failure mode stated as behaviour.


def _cte_bodies(sql: str) -> tuple[str, str]:
    """The vec and kw CTE bodies, each truncated at its LIMIT.

    Anything found in here is applied before the top-k cut; anything applied
    after would appear past the LIMIT, in the outer SELECT.
    """
    vec, _, rest = sql.partition("kw AS (")
    kw, _, _ = rest.partition("LIMIT %(pool)s")
    return vec.partition("LIMIT %(pool)s")[0], kw


def _searched_sql(where: dict | None) -> tuple[str, dict]:
    store, pool = _store()
    store.search("refund", [0.5, 0.25], k=3, where=where)
    sql, params = pool.cursor.calls[0]
    return sql, params


def test_no_filter_leaves_the_query_unpredicated():
    sql, params = _searched_sql(None)
    assert "document_id =" not in sql
    assert "@>" not in sql
    assert not [key for key in params if key.startswith("f_")]


def test_empty_where_is_the_same_query_as_no_where():
    assert _searched_sql({})[0] == _searched_sql(None)[0]


def test_document_id_filters_inside_both_ctes_before_the_top_k_cut():
    sql, params = _searched_sql({"document_id": "d1"})
    vec, kw = _cte_bodies(sql)
    assert "document_id = %(f_document_id)s" in vec
    assert "document_id = %(f_document_id)s" in kw
    assert params["f_document_id"] == "d1"


def test_document_id_uses_the_column_not_the_jsonb_blob():
    """chunks.document_id is an indexed column (db/init.sql); metadata is not."""
    sql, _ = _searched_sql({"document_id": "d1"})
    assert "@>" not in sql


def test_metadata_keys_filter_inside_both_ctes_by_containment():
    sql, params = _searched_sql({"source": "policy.pdf"})
    vec, kw = _cte_bodies(sql)
    assert "metadata @> %(f_metadata)s::jsonb" in vec
    assert "metadata @> %(f_metadata)s::jsonb" in kw
    assert isinstance(params["f_metadata"], Json)
    assert params["f_metadata"].obj == {"source": "policy.pdf"}


def test_document_id_and_metadata_combine():
    sql, params = _searched_sql({"document_id": "d1", "source": "policy.pdf"})
    vec, kw = _cte_bodies(sql)
    for body in (vec, kw):
        assert "document_id = %(f_document_id)s" in body
        assert "metadata @> %(f_metadata)s::jsonb" in body
    assert params["f_document_id"] == "d1"
    assert params["f_metadata"].obj == {"source": "policy.pdf"}


def test_kw_filter_is_anded_onto_the_existing_text_predicate():
    """The kw CTE already has a WHERE; the filter must not replace it."""
    _, kw = _cte_bodies(_searched_sql({"document_id": "d1"})[0])
    assert "tsv @@ plainto_tsquery" in kw


def test_filter_values_never_reach_the_sql_text():
    hostile = "'; DROP TABLE chunks; --"
    sql, params = _searched_sql({"document_id": hostile, "source": hostile})
    assert hostile not in sql
    assert params["f_document_id"] == hostile
    assert params["f_metadata"].obj == {"source": hostile}


def test_filter_keys_never_reach_the_sql_text():
    """Metadata keys travel inside one jsonb parameter, not as identifiers."""
    sql, params = _searched_sql({"weird key; --": "x"})
    assert "weird key" not in sql
    assert params["f_metadata"].obj == {"weird key; --": "x"}


# --- the outer SELECT ---------------------------------------------------
#
# Repeating the predicate outside the CTEs cannot change the result set (the
# joins already restrict it to vec/kw members), but it lets the planner use
# chunks_document_idx instead of scanning every chunk. The risk is purely
# syntactic: the existing outer WHERE is an OR, so an unparenthesised AND
# would bind to the second disjunct and quietly change the query.


def _outer(sql: str) -> str:
    """Everything past the CTE block. `SELECT c.id` occurs only there."""
    outer = sql.partition("\nSELECT c.id")[2]
    assert outer, "outer SELECT not found - did the query shape change?"
    return outer


def test_outer_disjunction_stays_parenthesised():
    """`A OR B AND pred` is `A OR (B AND pred)` - the bug this guards."""
    for where in (None, {"document_id": "d1"}):
        assert "(vec.id IS NOT NULL OR kw.id IS NOT NULL)" in _outer(_searched_sql(where)[0])


def test_outer_select_repeats_the_filter_qualified_by_alias():
    outer = _outer(_searched_sql({"document_id": "d1", "source": "policy.pdf"})[0])
    assert "AND c.document_id = %(f_document_id)s" in outer
    assert "AND c.metadata @> %(f_metadata)s::jsonb" in outer


def test_outer_select_is_unfiltered_when_there_is_no_filter():
    outer = _outer(_searched_sql(None)[0])
    assert "AND c.document_id" not in outer
    assert "@>" not in outer


def test_outer_filter_reuses_the_cte_parameters():
    """One bound value per filter key, however many times it appears."""
    _, params = _searched_sql({"document_id": "d1", "source": "policy.pdf"})
    assert sorted(k for k in params if k.startswith("f_")) == ["f_document_id", "f_metadata"]
