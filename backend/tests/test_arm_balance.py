"""The keyword arm must not evict the vector arm's own best hits.

Decision 17 fixed an arm that fired on nothing. It created the opposite
failure, and nothing in the suite measures it. Under OR semantics the arm
matches 232 of 376 chunks - 62% of the corpus - for a question-shaped input,
ordered by `ts_rank_cd` over commodity lexemes (`network`, `token`, `word`,
`order`). That ordering carries almost no signal, and RRF hands it exactly
the same authority as the vector arm's.

The arithmetic is the whole bug. At `RRF_K=60` over a pool of 24 the entire
rank spread is 1/61 .. 1/84, i.e. 27%. Membership in *both* arms is worth up
to 100%. Co-occurrence therefore outweighs every rank difference by roughly
4x, and a chunk the vector arm ranked 5th with a noise keyword hit beats the
chunk the vector arm ranked 1st with none.

Measured on the golden question below, the fused top 6 contained **zero**
chunks from the only paper that answers it, while vector ranks 1, 2 and 3
were all from that paper.

Weighting the arm down is not the fix: the weight needed to stop the
eviction is < 1 - (RRF_K+1)/(RRF_K+2) = 0.0161, which is an arm that can
only break ties. The contract below is inclusion instead - the vector arm's
top hits get guaranteed slots in the window, and the keyword arm competes
for the rest. Stated as behaviour, so a reserved-slot or an interleaving
implementation both satisfy it.

Scope, honestly: this does not flip the golden case. The passage that
answers it sits at vector rank 25 and no rank fusion reaches it - measured,
the model refuses on a vector-only top 6 too (README, evals). This module
fixes the retriever, not that question.
"""
from __future__ import annotations

from contextlib import contextmanager

from app.adapters.pgvector_store import RRF_K, PgVectorStore

# Arm rankings measured against the restored corpus for the golden question
# "If the network reads every token in parallel, how does it still know what
# order the words came in?" at pool = k*4 = 24. Ids are `<paper>/<chunk_index>`:
# A = 1706.03762v7.pdf (Attention - the only paper that answers it),
# B = 1810.04805v2.pdf (BERT), G = 2005.14165v4.pdf (GPT-3).
VEC_RANKED = [
    "A/5", "A/14", "A/15", "G/82", "B/16", "B/15", "B/53", "A/9", "A/41", "G/164",
    "A/3", "A/40", "B/14", "A/37", "G/6", "G/83", "B/50", "A/23", "G/111", "G/249",
    "G/9", "B/55", "B/13", "B/47",
]
KW_RANKED = [
    "G/81", "B/16", "B/13", "G/138", "G/164", "B/15", "B/53", "G/94", "G/101", "G/139",
    "B/52", "B/59", "G/82", "B/18", "G/140", "B/14", "G/84", "A/40", "B/6", "B/5",
    "G/211", "G/79", "B/50", "G/66",
]
K = 6


def _plain_rrf(vec_ranked: list[str], kw_ranked: list[str], k: int) -> list[str]:
    """The shipped fusion, in Python: the control case, not the contract.

    Keeps the diagnosis in the suite instead of in a commit message. If this
    ever stops evicting the vector arm's top hits, the premise of the fix has
    changed.
    """
    vec = {c: i + 1 for i, c in enumerate(vec_ranked)}
    kw = {c: i + 1 for i, c in enumerate(kw_ranked)}
    scored = {
        c: (1.0 / (RRF_K + vec[c]) if c in vec else 0.0)
        + (1.0 / (RRF_K + kw[c]) if c in kw else 0.0)
        for c in set(vec) | set(kw)
    }
    return sorted(scored, key=lambda c: (-scored[c], c))[:k]


def _paper(chunk_id: str) -> str:
    return chunk_id.partition("/")[0]


# --- the diagnosis, as a control case ------------------------------------


def test_plain_rrf_returns_nothing_from_the_paper_that_answers_the_question():
    """What the app does today. Vector ranks 1-3 are all `A`; none survive."""
    assert [c for c in _plain_rrf(VEC_RANKED, KW_RANKED, K) if _paper(c) == "A"] == []


def test_co_occurrence_outweighs_every_rank_difference_in_the_pool():
    """Why it happens, in one assertion.

    The best a rank difference can be worth across the whole pool is
    1/61 - 1/84. Being in both arms is worth up to a second 1/61 - which is
    nearly four times larger, so membership decides the ordering and rank
    only breaks ties within it.
    """
    widest_rank_gap = 1 / (RRF_K + 1) - 1 / (RRF_K + len(VEC_RANKED))
    dual_arm_bonus = 1 / (RRF_K + 1)
    assert dual_arm_bonus > 3 * widest_rank_gap


# --- the contract --------------------------------------------------------


def test_vector_reserved_slots_is_half_the_window():
    """Half the window is guaranteed to the vector arm, rounded up.

    Derived from k, not chosen: the point is that the arm which actually
    understands paraphrase keeps representation at every k, the same way
    decision 18 derives the floor instead of hardcoding it.
    """
    from app.adapters.pgvector_store import vector_reserved_slots

    assert vector_reserved_slots(6) == 3
    assert vector_reserved_slots(7) == 4
    assert vector_reserved_slots(1) == 1


def test_the_vector_arms_top_hits_are_never_evicted():
    """The defect, stated as the property that must hold."""
    from app.adapters.pgvector_store import fuse, vector_reserved_slots

    fused = fuse(VEC_RANKED, KW_RANKED, k=K)
    reserved = VEC_RANKED[: vector_reserved_slots(K)]
    assert set(reserved) <= set(fused)


def test_the_answering_paper_survives_fusion():
    """The behavioural consequence: the right document reaches the model.

    Not the same as answering the question - see the module docstring - but
    returning zero chunks from the only relevant paper is the retrieval bug
    underneath, and it is measurable without an API key.
    """
    from app.adapters.pgvector_store import fuse

    assert [c for c in fuse(VEC_RANKED, KW_RANKED, k=K) if _paper(c) == "A"]


def test_the_keyword_arm_still_shapes_the_window():
    """Guards the obvious wrong fix: deleting the arm.

    Reserving slots for the vector arm must not turn the retriever into
    vector-only search. The unreserved slots are still fused, so the window
    has to differ from the vector arm's own top k - otherwise the tests above
    pass for the wrong reason and decision 2 quietly became "vector-only".
    """
    from app.adapters.pgvector_store import fuse

    assert fuse(VEC_RANKED, KW_RANKED, k=K) != VEC_RANKED[:K]


def test_fusion_returns_exactly_k_distinct_chunks():
    from app.adapters.pgvector_store import fuse

    fused = fuse(VEC_RANKED, KW_RANKED, k=K)
    assert len(fused) == K
    assert len(set(fused)) == K


def test_fusion_is_deterministic():
    from app.adapters.pgvector_store import fuse

    assert fuse(VEC_RANKED, KW_RANKED, k=K) == fuse(VEC_RANKED, KW_RANKED, k=K)


def test_fusion_handles_an_arm_that_returned_nothing():
    """Either arm may come back empty; the other must still produce a window."""
    from app.adapters.pgvector_store import fuse

    assert fuse(VEC_RANKED, [], k=K) == VEC_RANKED[:K]
    assert fuse([], KW_RANKED, k=K) == KW_RANKED[:K]


# --- the SQL says the same thing -----------------------------------------
#
# `fuse` is the specification; Postgres does the work. These assert the two
# have not drifted apart, the way single_arm_floor mirrors 1/(RRF_K+rank).


class _FakeCursor:
    def __init__(self) -> None:
        self.sql = ""
        self.params: object = None

    def execute(self, sql: str, params: object = None) -> None:
        self.sql, self.params = sql, params

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


def _searched() -> _FakeCursor:
    pool = _FakePool()
    PgVectorStore(pool).search("refund policy", [0.5, 0.25], k=6)
    return pool.cursor


def test_reserved_slots_are_applied_before_the_outer_limit():
    """After `LIMIT %(k)s` the window is already cut - too late to reserve."""
    sql = _searched().sql
    head, _, tail = sql.partition("LIMIT %(k)s")
    assert "%(reserved)s" in head
    assert "%(reserved)s" not in tail


def test_the_reserved_count_travels_as_a_bound_parameter():
    from app.adapters.pgvector_store import vector_reserved_slots

    assert _searched().params["reserved"] == vector_reserved_slots(6)


def test_the_outer_disjunction_still_stays_parenthesised():
    """Unchanged from decision 13's guard; reserving slots must not undo it."""
    assert "(vec.id IS NOT NULL OR kw.id IS NOT NULL)" in _searched().sql


# --- the grounding floor follows the fusion ------------------------------


def test_the_floor_never_deletes_a_reserved_hit():
    """Decision 18's guarantee, restated against the new fusion.

    Reserving slots is pointless if the grounding floor then discards them.
    The thinnest reserved hit is vector rank `vector_reserved_slots(k)`,
    scoring 1/(RRF_K + that rank), and the derived floor must sit at or below
    it - otherwise retrieval guarantees a slot and grounding silently takes
    it away, which is the exact shape of the trap decision 18 closed.
    """
    from app.adapters.pgvector_store import single_arm_floor, worst_reserved_score

    for k in (1, 6, 7, 12):
        assert single_arm_floor(k) <= worst_reserved_score(k) + 1e-12
