from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    token_count: int | None = None
    metadata: dict | None = None
    # Vị trí ký tự bắt đầu của chunk trong text gốc (trước khi chunk). Dùng để map
    # Chunk <-> Provision (citation graph) theo giao vùng ký tự. Lấy từ
    # RecursiveCharacterTextSplitter(add_start_index=True) — thư viện tự tính bằng
    # text.find() có neo vị trí gần đúng, không phải tự dò lại nên không bị lệch
    # khi overlap tạo chuỗi trùng lặp gần nhau.
    char_start: int | None = None


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
            add_start_index=True,
        )

    def chunk(self, text: str, metadata: dict | None = None) -> list[TextChunk]:
        # create_documents() gọi split_text() y hệt bên trong (xem langchain_text_splitters
        # source) rồi bọc thêm start_index — nội dung/số lượng chunk không đổi so với
        # gọi split_text() trực tiếp như trước.
        docs = self._splitter.create_documents([text])
        return [
            TextChunk(
                content=doc.page_content,
                chunk_index=i,
                token_count=self._estimate_tokens(doc.page_content),
                metadata=metadata,
                char_start=doc.metadata.get("start_index"),
            )
            for i, doc in enumerate(docs)
            if doc.page_content.strip()
        ]

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        # Rough estimate: ~4 chars per token for English/Vietnamese
        return max(1, len(text) // 4)
