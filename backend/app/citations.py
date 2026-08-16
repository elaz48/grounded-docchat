"""What `[n]` means by the time the UI renders it.

The model cites *context block* numbers: one per retrieved chunk, [1]..[k].
Those are not a numbering the UI can show. An answer cites a handful of the
blocks, not all of them, and several blocks routinely come from the same
file - so block numbers leave gaps and repeat sources.

This module rewrites them into the contract the frontend relies on:

    citations[j] is the source of every `[j+1]` marker in text

which makes the inline numbers and the citation chips the same numbering by
construction, with one chip per source. See PLAN.md decision 14.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# The leading blank is part of the match so that dropping a marker does not
# leave a double space behind in the prose.
_MARKER = re.compile(r"([ \t]*)\[(\d+)\]")


@dataclass(frozen=True)
class CitedText:
    text: str
    citations: list[str]


def normalize_citations(text: str, sources: list[str]) -> CitedText:
    """Renumber block markers in `text` into deduplicated citation indices.

    `sources[i]` is the source of block `[i + 1]`, i.e. the retrieval order
    the blocks were shown to the model in.
    """
    citations: list[str] = []
    position: dict[str, int] = {}
    # Where the previous marker ended and what it was numbered, so that markers
    # which end up touching can be collapsed.
    previous_end, previous_number = -1, 0

    def rewrite(match: re.Match[str]) -> str:
        nonlocal previous_end, previous_number
        blank, block = match.group(1), int(match.group(2))
        touching = previous_end == match.start()
        previous_end = match.end()

        if not 0 < block <= len(sources):
            # A marker pointing at no block cites nothing. Dropping it beats
            # keeping a number that renumbering would make collide with a
            # real citation.
            return ""
        source = sources[block - 1]
        if source not in position:
            citations.append(source)
            position[source] = len(citations)

        number = position[source]
        if touching and previous_number == number:
            # Deduplication turned "[1][2]" into "[1] [1]"; the repeat carries
            # no information the first marker did not.
            return ""
        previous_number = number
        return f"{blank}[{number}]"

    return CitedText(text=_MARKER.sub(rewrite, text), citations=citations)
