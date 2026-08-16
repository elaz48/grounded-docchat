"""The citation contract: the inline [n] numbers and the chips are one numbering.

Backlog item 6 / PLAN.md decision 14. The mapping is pure text, so the whole
contract is asserted offline - no Claude, no keys, same as the rest of the suite.
"""
from __future__ import annotations

import re

from app.citations import normalize_citations

# Five retrieved blocks, three of them from the same file.
SOURCES = ["policy.pdf", "policy.pdf", "handbook.pdf", "policy.pdf", "shipping.pdf"]


def test_markers_are_renumbered_to_the_position_of_their_citation():
    cited = normalize_citations("Returns take 30 days [1], shipping is free [5].", SOURCES)
    assert cited.text == "Returns take 30 days [1], shipping is free [2]."
    assert cited.citations == ["policy.pdf", "shipping.pdf"]


def test_two_blocks_from_one_file_become_one_citation():
    """The reason the chips are deduped: [1] and [4] are both policy.pdf."""
    cited = normalize_citations("Refunds [1] are processed weekly [4].", SOURCES)
    assert cited.text == "Refunds [1] are processed weekly [1]."
    assert cited.citations == ["policy.pdf"]


def test_repeated_markers_collapse_where_they_touch():
    """Two blocks from one file next to each other ("[1][2]") would render as
    "[1] [1]" once deduplicated, which is noise: the second says nothing."""
    assert normalize_citations("Both blocks agree [1][2].", SOURCES).text == (
        "Both blocks agree [1]."
    )
    assert normalize_citations("Both blocks agree [1] [2].", SOURCES).text == (
        "Both blocks agree [1]."
    )


def test_the_same_source_cited_again_later_keeps_its_marker():
    """Only touching repeats collapse - a second claim still carries a source."""
    cited = normalize_citations("Refunds run 30 days [1]; returns are free [2].", SOURCES)
    assert cited.text == "Refunds run 30 days [1]; returns are free [1]."
    assert cited.citations == ["policy.pdf"]


def test_numbering_follows_the_answer_not_the_block_order():
    cited = normalize_citations("Shipping [5] is separate from refunds [1].", SOURCES)
    assert cited.text == "Shipping [1] is separate from refunds [2]."
    assert cited.citations == ["shipping.pdf", "policy.pdf"]


def test_marker_past_the_end_of_the_context_is_dropped():
    """A hallucinated block number cites nothing, and renumbering would make it
    collide with a real citation - so it must not survive as a number."""
    cited = normalize_citations("Unsupported [9] but this holds [5].", SOURCES)
    assert cited.text == "Unsupported but this holds [1]."
    assert cited.citations == ["shipping.pdf"]


def test_dropping_a_marker_leaves_the_prose_intact():
    assert normalize_citations("A claim [0] with no source.", SOURCES).text == (
        "A claim with no source."
    )


def test_answer_without_markers_keeps_its_text_and_cites_nothing():
    cited = normalize_citations("I can't answer that from the uploaded documents.", SOURCES)
    assert cited.text == "I can't answer that from the uploaded documents."
    assert cited.citations == []


def test_markdown_structure_survives_renumbering():
    """M4 renders these answers as markdown; rewriting must not touch the syntax."""
    answer = "**Refunds**\n\n- within 30 days [1]\n- free shipping [5]\n\n$E = mc^2$ [3]"
    cited = normalize_citations(answer, SOURCES)
    assert cited.text == (
        "**Refunds**\n\n- within 30 days [1]\n- free shipping [2]\n\n$E = mc^2$ [3]"
    )
    assert cited.citations == ["policy.pdf", "shipping.pdf", "handbook.pdf"]


def test_every_marker_that_survives_indexes_a_citation():
    """The invariant the UI depends on: [n] is always citations[n - 1]."""
    messy = "Mixed [4] claims [99] across [2] blocks [1] and [5] and [4] again."
    cited = normalize_citations(messy, SOURCES)
    rendered = [int(n) for n in re.findall(r"\[(\d+)\]", cited.text)]
    assert rendered  # the answer still cites something
    assert all(1 <= n <= len(cited.citations) for n in rendered)
    assert len(cited.citations) == len(set(cited.citations))
