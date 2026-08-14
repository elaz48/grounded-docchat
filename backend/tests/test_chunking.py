from app.chunking import chunk_document, chunk_text


def test_packs_paragraphs_up_to_target():
    text = "para one\n\npara two\n\npara three"
    assert chunk_text(text, target_chars=1000) == ["para one\n\npara two\n\npara three"]


def test_splits_when_target_exceeded():
    text = "\n\n".join(["a" * 500, "b" * 500, "c" * 500])
    chunks = chunk_text(text, target_chars=800, overlap_chars=100)
    assert len(chunks) >= 2
    # overlap: the tail of chunk 1 reappears at the head of chunk 2
    assert chunks[0][-50:] in chunks[1]


def test_oversized_paragraph_is_hard_split():
    chunks = chunk_text("x" * 3000, target_chars=1000, overlap_chars=100)
    assert all(len(c) <= 1000 for c in chunks)
    assert sum(len(c) for c in chunks) >= 3000  # nothing lost


def test_chunk_document_carries_metadata():
    chunks = chunk_document("doc-1", "hello\n\nworld", source="a.txt", target_chars=6)
    assert chunks[0].metadata["source"] == "a.txt"
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))
