"""
Retriever node: runs hybrid (dense + graph) search and populates state.

dense_results  — raw Qdrant ANN hits
graph_results  — Neo4j-expanded chunks (NEXT_CHUNK / REFERENCES traversal)
merged_results — hybrid-scored union, sorted by descending score

Mỗi lượt node chạy: đúng 1 lời gọi Qdrant (`_dense_search`) và tối đa 1 lời gọi
`_graph_search` (Neo4j); hai kết quả đó được trộn bằng `HybridRetriever.merge()`.

search_mode="vector" → dense-only: KHÔNG chạm Neo4j ở bất kỳ đâu trong node này;
graph_results = [] và merged_results = dense_results xếp theo điểm cosine giảm dần.
"""

import asyncio
from dataclasses import replace

from app.agents.state import AgentState
from app.ingestion.embedder import get_embedder
from app.rag.citation_retriever import graph_augmented_search
from app.rag.retriever import HybridRetriever, RetrievedChunk


def _drop_excluded(
    chunks: list[RetrievedChunk], excluded_document_ids: list[str] | None
) -> list[RetrievedChunk]:
    """Chốt chặn cuối ở node: bỏ chunk thuộc tài liệu bị loại trừ (vd đang tắt).

    Filter chính nằm ở Qdrant/Neo4j (HybridRetriever) và citation_retriever; hàm này
    chỉ để một chunk lọt filter phía DB (payload/node lệch dữ liệu) vẫn không vào
    state. None/rỗng → trả nguyên danh sách (hành vi cũ).
    """
    if not excluded_document_ids:
        return chunks
    excluded = set(excluded_document_ids)
    return [c for c in chunks if c.document_id not in excluded]


async def retriever_node(state: AgentState) -> AgentState:
    query = state.get("rewritten_query") or state["query"]

    embedder = get_embedder()
    retriever = HybridRetriever()

    # embedder.embed_query (sync OpenAI client), _dense_search (sync httpx.Client)
    # và _graph_search (sync Neo4j driver) đều block trên I/O mạng. Chạy qua
    # asyncio.to_thread để không giữ event loop FastAPI trong lúc chờ — nếu không,
    # mỗi query ở đây sẽ treo mọi request đồng thời khác cho tới khi xong.
    query_embedding = await asyncio.to_thread(embedder.embed_query, query)

    document_ids = state.get("document_ids")
    owner_id = state.get("owner_id")  # data isolation: None = admin/không filter
    score_threshold = state.get("similarity_threshold")  # ngưỡng tương đồng từ UI
    # Tài liệu phải loại khỏi truy hồi (vd is_active=False). Trường NotRequired trong
    # AgentState → BẮT BUỘC đọc bằng .get(): thiếu key thì None = không loại gì.
    # PHẢI truyền vào MỌI lời gọi bên dưới (_dense_search, _graph_search, merge,
    # graph_augmented_search): node này tự ghép các bước chứ không đi qua retrieve().
    excluded_document_ids = state.get("excluded_document_ids")
    # Chỉ đúng chuỗi "vector" mới là dense-only. None/"hybrid"/"keyword"/"advanced" (và
    # mọi giá trị khác) giữ nguyên đường hybrid bên dưới. Đọc lại từ state ở MỖI lần
    # node chạy nên vòng rewriter → retriever vẫn ở đúng chế độ.
    vector_only = state.get("search_mode") == "vector"

    # Dense seeds (Qdrant)
    dense_results = await asyncio.to_thread(
        retriever._dense_search,
        query_embedding,
        document_ids=document_ids,
        owner_id=owner_id,
        score_threshold=score_threshold,
        excluded_document_ids=excluded_document_ids,
    )
    dense_results = _drop_excluded(dense_results, excluded_document_ids)

    if vector_only:
        # Dense-only: node này có 2 chỗ chạm Neo4j — `_graph_search` (nhánh hybrid bên
        # dưới) và `graph_augmented_search` (chỉ khi "advanced"). Nhánh này bỏ chỗ đầu
        # và không gọi `merge()` (không có kết quả graph để trộn); chỗ thứ hai không
        # chạy vì search_mode không thể vừa "vector" vừa "advanced".
        # Bộ lọc bảo mật không đổi: dense_results ở trên đã qua filter Qdrant
        # (owner_id / document_ids / excluded_document_ids) và `_drop_excluded`.
        # Điểm là cosine THÔ của Qdrant, KHÔNG chuẩn hoá/nhân trọng số 0.7 như hybrid.
        # Bản sao (replace) để merged_results không dùng chung object với dense_results
        # — giống đường hybrid, nơi `merge()` trả về bản sao riêng.
        graph_results: list[RetrievedChunk] = []
        merged_results = _drop_excluded(
            sorted((replace(c) for c in dense_results), key=lambda x: x.score, reverse=True),
            excluded_document_ids,
        )
    else:
        # Graph expansion (Neo4j) — returns {} if Neo4j is unavailable
        seed_ids = [r.chunk_id for r in dense_results]
        graph_map = await asyncio.to_thread(
            retriever._graph_search,
            seed_ids,
            document_ids=document_ids,
            owner_id=owner_id,
            excluded_document_ids=excluded_document_ids,
        )
        graph_results = _drop_excluded(
            [chunk for chunk, _ in graph_map.values()], excluded_document_ids
        )

        # Merge + hybrid score — trộn CHÍNH hai kết quả vừa lấy ở trên. KHÔNG gọi
        # `retriever.retrieve()`: nó tự chạy lại `_dense_search` + `_graph_search`, tức
        # gấp đôi lời gọi Qdrant/Neo4j mỗi lượt (và nhân lên theo vòng rewriter).
        # `merge()` là hàm thuần, sync, không I/O → gọi thẳng, không cần to_thread.
        # - Truyền `graph_map` (dict của `_graph_search`), không phải list `graph_results`.
        # - BẮT BUỘC truyền `excluded_document_ids`: mặc định None = không loại gì, và
        #   `_drop_excluded` ngay dưới sẽ che mất lỗi quên tham số ở đầu ra.
        # - `dense_results` đã qua `_drop_excluded` nên mẫu số chuẩn hoá (điểm dense lớn
        #   nhất) chỉ tính trên chunk được phép: chunk của tài liệu bị loại lọt filter
        #   Qdrant không ảnh hưởng điểm của chunk còn lại.
        merged_results = retriever.merge(
            dense_results, graph_map, excluded_document_ids=excluded_document_ids
        )
        merged_results = _drop_excluded(merged_results, excluded_document_ids)

    # Chế độ "Nâng cao": thêm graph-augmented retrieval qua Provision layer (citation
    # graph) — traverse VIEN_DAN 1-2 hop từ Provision khớp dense seeds. ĐÃ qua gate
    # plan Pro ở route (core/plan_gate.py::require_advanced_search_access) trước khi
    # state tới đây, nên không cần check lại quyền ở node này.
    citation_graph_path: list[dict] = []
    citation_graph_nodes: list[dict] = []
    suggested_documents: list[dict] = []
    if state.get("search_mode") == "advanced" and dense_results:
        citation_result = await asyncio.to_thread(
            graph_augmented_search,
            [r.chunk_id for r in dense_results],
            document_ids,
            owner_id,
            excluded_document_ids=excluded_document_ids,
        )
        citation_graph_path = citation_result.citation_graph_path
        citation_graph_nodes = citation_result.citation_graph_nodes
        suggested_documents = citation_result.suggested_documents

        # Dedupe theo chunk_id với hybrid merged_results — giữ score cao hơn (Provision
        # neo/liên quan có thể trùng chunk đã có trong merged_results từ dense/graph cũ).
        combined: dict[str, RetrievedChunk] = {c.chunk_id: c for c in merged_results}
        for chunk in citation_result.context_chunks:
            existing = combined.get(chunk.chunk_id)
            if existing is None or chunk.score > existing.score:
                combined[chunk.chunk_id] = chunk
        merged_results = _drop_excluded(
            sorted(combined.values(), key=lambda x: x.score, reverse=True),
            excluded_document_ids,
        )

    return {
        **state,
        "dense_results": dense_results,
        "graph_results": graph_results,
        "merged_results": merged_results,
        "citation_graph_path": citation_graph_path,
        "citation_graph_nodes": citation_graph_nodes,
        "suggested_documents": suggested_documents,
    }
