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
