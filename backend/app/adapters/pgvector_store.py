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

_HYBRID_SQL = """
WITH vec AS (
    SELECT id, row_number() OVER (ORDER BY embedding <=> %(qvec)s::vector) AS rank
    FROM chunks
    ORDER BY embedding <=> %(qvec)s::vector
    LIMIT %(pool)s
),
kw AS (
    SELECT id, row_number() OVER (
        ORDER BY ts_rank_cd(tsv, plainto_tsquery('english', %(qtext)s)) DESC
    ) AS rank
    FROM chunks
    WHERE tsv @@ plainto_tsquery('english', %(qtext)s)
    LIMIT %(pool)s
)
SELECT c.id, c.document_id, c.content, c.metadata,
       COALESCE(1.0 / (%(rrf_k)s + vec.rank), 0)
     + COALESCE(1.0 / (%(rrf_k)s + kw.rank), 0) AS score
FROM chunks c
LEFT JOIN vec ON vec.id = c.id
LEFT JOIN kw  ON kw.id  = c.id
WHERE vec.id IS NOT NULL OR kw.id IS NOT NULL
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
        # TODO(M2): translate `where` into SQL predicates (document_id filter first).
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                _HYBRID_SQL,
                {
                    "qvec": Vector(query_embedding),
                    "qtext": query_text,
                    "pool": k * 4,
                    "rrf_k": RRF_K,
                    "k": k,
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
