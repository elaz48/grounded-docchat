"""The keyword arm must fire on question-shaped input.

Regression tests for the two paraphrase cases that failed the golden evals
(evals/golden.jsonl): "If the network reads every token in parallel..." and
"How can a model take both the words before and the words after...". Both
came back `grounded=false` with no citations.

The grounding floor was not the cause: every returned hit scored exactly
1/(60+rank) for ranks 1-6, i.e. 0.01639 down to 0.01515, all above the 0.015
floor. The cause is one word in the SQL - `plainto_tsquery` ANDs every
lexeme, so a 10-13 word question matches no chunk at all and the hybrid
silently degrades to vector-only. Measured on the restored corpus: 11 of the
12 answerable golden questions produced *zero* keyword hits.

The shape tests below run offline against the generated SQL. The behavioural
ones need the restored corpus and are skipped unless DOCCHAT_LIVE_DB is set,
so `pytest` stays offline and under a second (CLAUDE.md).
"""
from __future__ import annotations

import os
from contextlib import contextmanager

import pytest
from app.adapters.pgvector_store import PgVectorStore

# The two golden cases this module exists for, with the paper that answers
# each. Written as paraphrases on purpose: they share no distinctive term
# with the chunk that answers them, which is exactly what the vector arm is
# for and what the keyword arm must not sabotage by returning nothing.
PARAPHRASE_CASES = [
    pytest.param(
        "If the network reads every token in parallel, how does it still know "
        "what order the words came in?",
        id="positional-encoding",
    ),
    pytest.param(
        "How can a model take both the words before and the words after a position "
        "into account at the same time, when a standard language model only ever "
        "looks backwards?",
        id="bidirectional-context",
    ),
]


# --- offline: the shape of the generated SQL -----------------------------


class _FakeCursor:
    def __init__(self) -> None:
        self.sql = ""

    def execute(self, sql: str, params: object = None) -> None:
        self.sql = sql

    def fetchall(self) -> list[tuple]:
        return []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def __init__(self) -> None:
        self.cursor = _FakeCursor()

    @contextmanager
    def connection(self):
        yield _FakeConnection(self.cursor)


def _generated_sql(where: dict | None = None) -> str:
    pool = _FakePool()
    PgVectorStore(pool).search("refund policy", [0.5, 0.25], k=6, where=where)
    return pool.cursor.sql


def _kw_body(sql: str) -> str:
    """The kw CTE up to its LIMIT - everything applied before the top-k cut."""
    return sql.partition("kw AS (")[2].partition("LIMIT %(pool)s")[0]


def test_keyword_arm_does_not_and_the_question_lexemes():
    """`tsv @@ plainto_tsquery(q)` requires a chunk to contain *every* lexeme.

    That is the bug: on a 13-lexeme question no chunk qualifies, the arm
    returns nothing, and RRF fuses one arm with the empty set.
    """
    assert "tsv @@ plainto_tsquery" not in _kw_body(_generated_sql())


def test_keyword_arm_or_joins_the_lexemes():
    """Postgres does the parsing and stemming; we only swap the operator."""
    assert "' & ', ' | '" in _generated_sql()


def test_keyword_arm_still_ranks_by_cover_density():
    """OR decides *membership*; ts_rank_cd still decides order within the arm."""
    assert "ts_rank_cd" in _kw_body(_generated_sql())


def test_keyword_arm_orders_before_its_limit():
    """`LIMIT` with no statement-level ORDER BY takes an arbitrary slice.

    The window's ORDER BY numbers the rows, it does not order the output.
    The vec CTE has always repeated its ordering above the LIMIT; the kw CTE
    did not, which was harmless only while the arm returned 0-1 rows. Under
    OR semantics it matches hundreds, so the pool must be the top of the
    ranking and not any 24 rows the planner happens to emit.
    """
    assert _kw_body(_generated_sql()).count("ORDER BY ts_rank_cd") == 2


def test_or_semantics_survive_the_where_filter():
    """The M2 pre-filter predicates still sit inside the arm (decision 13)."""
    kw = _kw_body(_generated_sql({"document_id": "d1"}))
    assert "document_id = %(f_document_id)s" in kw
    assert "ts_rank_cd" in kw


# --- live: the arm actually fires on the restored corpus -----------------

LIVE_DSN = os.environ.get("DOCCHAT_LIVE_DB")
live = pytest.mark.skipif(not LIVE_DSN, reason="set DOCCHAT_LIVE_DB to run against the corpus")


@pytest.fixture(scope="module")
def live_cursor():
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(LIVE_DSN) as conn, conn.cursor() as cur:
        yield cur


@live
@pytest.mark.live
@pytest.mark.parametrize("question", PARAPHRASE_CASES)
def test_keyword_arm_returns_rows_for_a_paraphrase_question(live_cursor, question):
    """Zero rows here is the whole failure: RRF then has nothing to fuse."""
    from app.adapters.pgvector_store import KW_TSQUERY

    live_cursor.execute(
        f"SELECT count(*) FROM chunks WHERE tsv @@ {KW_TSQUERY}", {"qtext": question}
    )
    assert live_cursor.fetchone()[0] > 0


@live
@pytest.mark.live
def test_and_semantics_are_what_returned_nothing(live_cursor):
    """The control case: the old predicate on the same corpus and question.

    Keeps the diagnosis in the suite rather than in a commit message - if
    this ever starts returning rows, the premise of the fix has changed.
    """
    live_cursor.execute(
        "SELECT count(*) FROM chunks WHERE tsv @@ plainto_tsquery('english', %(qtext)s)",
        {"qtext": PARAPHRASE_CASES[1].values[0]},
    )
    assert live_cursor.fetchone()[0] == 0
