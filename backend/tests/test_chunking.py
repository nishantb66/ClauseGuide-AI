from app.services.chunker import LegalChunker
from app.services.text_cleaner import CleanedPage


def test_chunker_creates_overlapping_chunks() -> None:
    words = " ".join([f"word{i}" for i in range(2000)])
    page = CleanedPage(page_number=1, raw_text=words, cleaned_text=words)

    chunker = LegalChunker(target_tokens=300, overlap_tokens=50)
    chunks = chunker.chunk_pages([page])

    assert len(chunks) > 1
    assert chunks[0].token_count <= 300
    assert chunks[-1].token_count <= 300
    assert chunks[0].chunk_index == 0


def test_chunker_detects_clause_type() -> None:
    text = "TERMINATION\nThe company may terminate this agreement with 30 days notice period."
    page = CleanedPage(page_number=1, raw_text=text, cleaned_text=text)

    chunker = LegalChunker()
    chunks = chunker.chunk_pages([page])

    assert chunks
    assert chunks[0].clause_type in {"termination", "notice_period"}
