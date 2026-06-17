
from app.ingestion.chunker import DocumentChunker


def test_chunk_basic_text():
    chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)
    text = "Hello world. " * 50
    chunks = chunker.chunk(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.content) <= 120  # Allow some overlap


def test_chunk_index_sequential():
    chunker = DocumentChunker(chunk_size=200, chunk_overlap=50)
    text = "This is a test sentence. " * 100
    chunks = chunker.chunk(text)
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i


def test_chunk_empty_text():
    chunker = DocumentChunker()
    chunks = chunker.chunk("")
    assert chunks == []


def test_chunk_short_text():
    chunker = DocumentChunker(chunk_size=800, chunk_overlap=200)
    text = "Short document."
    chunks = chunker.chunk(text)
    assert len(chunks) == 1
    assert chunks[0].content == text


def test_chunk_token_count():
    chunker = DocumentChunker()
    text = "A" * 400
    chunks = chunker.chunk(text)
    for chunk in chunks:
        assert chunk.token_count is not None
        assert chunk.token_count > 0
