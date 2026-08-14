"""Retrieval assertions that actually assert something.

With random mock vectors these tests would be decorative (any doc can come
back at any rank). placeborag's controllable geometry makes rank order a
real, stable assertion - offline.
"""


def test_related_ranks_above_unrelated(seeded_store):
    hits = seeded_store.search("refund policy", query_embedding=[0.0], k=3)
    sources = [h.chunk.metadata["source"] for h in hits]
    assert sources[0] == "policy.pdf"


def test_retrieval_is_deterministic(seeded_store):
    first = [h.chunk.id for h in seeded_store.search("refund policy", [0.0], k=3)]
    second = [h.chunk.id for h in seeded_store.search("refund policy", [0.0], k=3)]
    assert first == second


def test_metadata_filter_narrows_results(seeded_store):
    hits = seeded_store.search("refund policy", [0.0], k=5, where={"source": "shipping.pdf"})
    assert {h.chunk.metadata["source"] for h in hits} == {"shipping.pdf"}


def test_filter_narrows_by_document_id_too(seeded_store):
    """`where` addresses the document_id column as well as metadata keys."""
    hits = seeded_store.search("refund policy", [0.0], k=5, where={"document_id": "d2"})
    assert {h.chunk.document_id for h in hits} == {"d2"}


def test_a_filtered_match_below_the_top_k_cut_is_still_returned(seeded_store):
    """Pre-filtering: the filter runs before k is applied, so a match that
    ranks below the cut for the unfiltered query still comes back.

    'shipping.pdf' is the worst match for "refund policy" of the three seeded
    chunks - with k=2 it never survives an unfiltered top-k."""
    top_two = seeded_store.search("refund policy", [0.0], k=2)
    assert "shipping.pdf" not in [h.chunk.metadata["source"] for h in top_two]

    hits = seeded_store.search("refund policy", [0.0], k=2, where={"source": "shipping.pdf"})
    assert [h.chunk.metadata["source"] for h in hits] == ["shipping.pdf"]


def test_post_filtering_would_under_return_which_is_why_we_pre_filter(post_filter_store):
    """The control case (PLAN.md decision 13).

    Identical data and query; the only difference is that the filter runs
    after the top-k cut. The matching chunk exists and is never returned -
    the user sees 'nothing found' about a document they can see in the
    sidebar. This is the bug the SQL predicates in the CTEs avoid."""
    hits = post_filter_store.search("refund policy", [0.0], k=2, where={"source": "shipping.pdf"})
    assert hits == []
