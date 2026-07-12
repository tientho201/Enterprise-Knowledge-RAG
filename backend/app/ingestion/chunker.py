from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    token_count: int | None = None
    metadata: dict | None = None


class DocumentChunker:
    """
    Splits documents into chunks using RecursiveCharacterTextSplitter.
    Preserves semantic boundaries: avoids splitting legal clauses or code blocks.
    """

    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ):
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.chunk_overlap = chunk_overlap or settings.CHUNK_OVERLAP
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", "! ", "? ", " ", ""],
        )

    def chunk(self, text: str, metadata: dict | None = None) -> list[TextChunk]:
        raw_chunks = self._splitter.split_text(text)
        return [
            TextChunk(
                content=chunk,
                chunk_index=i,
                token_count=self._estimate_tokens(chunk),
                metadata=metadata,
            )
            for i, chunk in enumerate(raw_chunks)
            if chunk.strip()
        ]

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        # Rough estimate: ~4 chars per token for English/Vietnamese
        return max(1, len(text) // 4)
