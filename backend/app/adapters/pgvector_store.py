"""Postgres + pgvector behind the VectorStore and DocumentStore ports.

Hybrid = HNSW cosine ranking fused with tsvector keyword ranking via
Reciprocal Rank Fusion (RRF, k=60). Postgres gives us BM25-ish keyword
search for free, so hybrid costs no extra service (PLAN.md decision log).

Score convention: RRF scores, higher is better - matching the app-wide
convention declared in ports.py.

Type adaptation is registered once, on the pool (PLAN.md decision 11):
psycopg will not bind a bare dict to JSONB or a bare list to vector, and
both failures only surface against a live database.
"""
from __future__ import annotations

from typing import Any

from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

from ..ports import Chunk, Document, RetrievedChunk

RRF_K = 60

# The `{...}_filter` slots are the only interpolated parts, and they are
# assembled from the fixed templates in _filter_predicates() - never from
# caller input, which travels as bound parameters. Asserted in
# test_pgvector_adapter.py::test_filter_values_never_reach_the_sql_text.
#
# The outer WHERE keeps its disjunction parenthesised: `A OR B AND pred`
# parses as `A OR (B AND pred)`, which would quietly stop filtering the vec
# arm. Asserted in test_outer_disjunction_stays_parenthesised.
_HYBRID_SQL = """
WITH vec AS (
    SELECT id, row_number() OVER (ORDER BY embedding <=> %(qvec)s::vector) AS rank
    FROM chunks
    {vec_filter}
    ORDER BY embedding <=> %(qvec)s::vector
    LIMIT %(pool)s
),
kw AS (
    SELECT id, row_number() OVER (
        ORDER BY ts_rank_cd(tsv, plainto_tsquery('english', %(qtext)s)) DESC
    ) AS rank
    FROM chunks
    WHERE tsv @@ plainto_tsquery('english', %(qtext)s){kw_filter}
    LIMIT %(pool)s
)
SELECT c.id, c.document_id, c.content, c.metadata,
       COALESCE(1.0 / (%(rrf_k)s + vec.rank), 0)
     + COALESCE(1.0 / (%(rrf_k)s + kw.rank), 0) AS score
FROM chunks c
LEFT JOIN vec ON vec.id = c.id
LEFT JOIN kw  ON kw.id  = c.id
WHERE (vec.id IS NOT NULL OR kw.id IS NOT NULL){outer_filter}
ORDER BY score DESC
LIMIT %(k)s;
"""

_UPSERT_CHUNK_SQL = """
INSERT INTO chunks (id, document_id, chunk_index, content, metadata, embedding)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE
    SET content = EXCLUDED.content,
        metadata = EXCLUDED.metadata,
        embedding = EXCLUDED.embedding
"""

_CREATE_DOCUMENT_SQL = """
INSERT INTO documents (id, filename)
VALUES (%s, %s)
ON CONFLICT (id) DO NOTHING
"""

_LIST_DOCUMENTS_SQL = """
SELECT d.id, d.filename, count(c.id) AS chunk_count
FROM documents d
LEFT JOIN chunks c ON c.document_id = d.id
GROUP BY d.id, d.filename, d.created_at
ORDER BY d.created_at DESC
"""


def _configure(conn: Connection) -> None:
    """Teach each pooled connection the pgvector types."""
    register_vector(conn)


def _filter_predicates(where: dict[str, Any] | None) -> tuple[list[str], dict[str, Any]]:
    """Translate a `where` mapping into SQL predicates plus bound parameters.

    `document_id` is matched against the column of that name, which is
    indexed (db/init.sql); every other key is matched by JSONB containment
    on `metadata`. Keys and values both travel as parameters - the metadata
    keys ride inside a single jsonb value - so nothing a caller supplies is
    ever interpolated into SQL text.

    Each predicate carries a `{t}` slot for a table alias, because the same
    predicate is emitted unqualified inside the CTEs (where `chunks` is the
    only table) and as `c.`-qualified in the outer SELECT.
    """
    if not where:
        return [], {}

    predicates: list[str] = []
    params: dict[str, Any] = {}
    metadata = dict(where)

    document_id = metadata.pop("document_id", None)
    if document_id is not None:
        predicates.append("{t}document_id = %(f_document_id)s")
        params["f_document_id"] = document_id
    if metadata:
        predicates.append("{t}metadata @> %(f_metadata)s::jsonb")
        params["f_metadata"] = Json(metadata)
    return predicates, params


def _hybrid_sql(predicates: list[str]) -> str:
    """Apply the filter inside both CTEs, above their LIMIT.

    That placement is the whole point (PLAN.md decision 13): filtering after
    the top-k cut returns fewer rows than asked for - sometimes none - even
    when plenty of matching chunks exist.

    The outer SELECT repeats the predicate. That cannot change the result -
    the joins already restrict it to rows the CTEs returned - but it lets
    the planner reach chunks_document_idx instead of scanning every chunk.
    """
    if not predicates:
        return _HYBRID_SQL.format(vec_filter="", kw_filter="", outer_filter="")

    cte = [p.format(t="") for p in predicates]
    outer = [p.format(t="c.") for p in predicates]
    return _HYBRID_SQL.format(
        vec_filter="WHERE " + " AND ".join(cte),
        kw_filter="".join(f"\n      AND {p}" for p in cte),
        outer_filter="".join(f"\n  AND {p}" for p in outer),
    )


class PgVectorStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    @classmethod
    def from_url(cls, database_url: str) -> PgVectorStore:
        return cls(ConnectionPool(database_url, open=True, configure=_configure))

    # --- DocumentStore -------------------------------------------------

    def create_document(self, document_id: str, filename: str) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(_CREATE_DOCUMENT_SQL, (document_id, filename))

    def list_documents(self) -> list[Document]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(_LIST_DOCUMENTS_SQL)
            rows = cur.fetchall()
        return [Document(id=r[0], filename=r[1], chunk_count=int(r[2])) for r in rows]

    # --- VectorStore ---------------------------------------------------

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                cur.execute(
                    _UPSERT_CHUNK_SQL,
                    (
                        chunk.id,
                        chunk.document_id,
                        chunk.metadata.get("chunk_index", 0),
                        chunk.content,
                        Json(chunk.metadata),
                        Vector(embedding),
                    ),
                )

    def search(
        self,
        query_text: str,
        query_embedding: list[float],
        k: int = 6,
        where: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        predicates, filter_params = _filter_predicates(where)
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                _hybrid_sql(predicates),
                {
                    "qvec": Vector(query_embedding),
                    "qtext": query_text,
                    "pool": k * 4,
                    "rrf_k": RRF_K,
                    "k": k,
                    **filter_params,
                },
            )
            rows = cur.fetchall()
        return [
            RetrievedChunk(
                chunk=Chunk(id=r[0], document_id=r[1], content=r[2], metadata=r[3]),
                score=float(r[4]),
            )
            for r in rows
        ]
