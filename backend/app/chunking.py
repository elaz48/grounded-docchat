"""Paragraph-packing chunker with overlap.

Deliberately simple (PLAN.md, decision log): split on blank lines, pack
paragraphs up to a target size, carry a character overlap between chunks so
answers spanning a boundary still retrieve. Oversized single paragraphs are
hard-split. Heading lines are kept with the paragraph that follows them.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from .ports import Chunk

_BLANK = re.compile(r"\n\s*\n")


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _BLANK.split(text) if p.strip()]


def chunk_text(text: str, *, target_chars: int = 1200, overlap_chars: int = 150) -> list[str]:
    paragraphs = split_paragraphs(text)
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(para) > target_chars:
            # flush, then hard-split the oversized paragraph
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(para), target_chars - overlap_chars):
                chunks.append(para[i : i + target_chars])
            continue
        if current and len(current) + len(para) + 2 > target_chars:
            chunks.append(current)
            current = current[-overlap_chars:] if overlap_chars else ""
        current = f"{current}\n\n{para}".strip() if current else para

    if current:
        chunks.append(current)
    return chunks


def chunk_document(
    document_id: str, text: str, *, source: str, target_chars: int = 1200,
    overlap_chars: int = 150, extra_metadata: dict[str, Any] | None = None,
) -> list[Chunk]:
    pieces = chunk_text(text, target_chars=target_chars, overlap_chars=overlap_chars)
    return [
        Chunk(
            id=str(uuid.uuid4()),
            document_id=document_id,
            content=piece,
            metadata={"source": source, "chunk_index": i, **(extra_metadata or {})},
        )
        for i, piece in enumerate(pieces)
    ]
