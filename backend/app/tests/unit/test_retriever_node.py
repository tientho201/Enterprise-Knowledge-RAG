"""retriever_node: truyền `excluded_document_ids` xuống MỌI nhánh truy hồi, và mỗi lượt
chỉ gọi Qdrant / Neo4j MỘT lần (T24).

Tài liệu đang tắt (Document.is_active=False) được ChatService đưa vào
state["excluded_document_ids"]. Node tự ghép `_dense_search` → `_graph_search` →
`merge()` (không đi qua `HybridRetriever.retrieve`, vì `retrieve()` chạy lại cả hai
lượt tìm kiếm), nên chỉ cần một lời gọi quên tham số là tài liệu tắt rò vào context.

Hai lớp kiểm:

1. HybridRetriever GIẢ ghi lại tham số (fixture `rec`) — khoá hợp đồng tham số của
   từng lời gọi. `merge` của bản giả ghi lại lời gọi rồi chạy `HybridRetriever.merge`
   THẬT, nên `merged_results` ở lớp này là điểm hybrid thật.
2. HybridRetriever THẬT, Qdrant (httpx) và Neo4j driver giả (fixture `infra`) — đếm số
   lời gọi mạng, đối chiếu kết quả với `retrieve()` (đường node dùng trước T24), và
   đếm WARNING khi Neo4j chết.

Không cần Qdrant/Neo4j/OpenAI thật.
"""

import logging
import random

import pytest

import app.rag.graph_client as graph_client
import app.rag.retriever as rag_retriever_module
from app.agents import retriever as retriever_module
from app.agents.retriever import retriever_node
from app.rag.citation_retriever import CitationGraphResult
from app.rag.retriever import HybridRetriever, RetrievedChunk

EMBEDDING = [0.1, 0.2, 0.3]
DENSE_WEIGHT = 0.7
GRAPH_WEIGHT = 0.3


class _Weights:
    """Đủ để chạy `HybridRetriever.merge` THẬT mà không dựng retriever (không I/O)."""

    dense_weight = DENSE_WEIGHT
    graph_weight = GRAPH_WEIGHT


def _chunk(chunk_id: str, document_id: str, score: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        document_name=f"{document_id}.pdf",
        content=f"content of {chunk_id}",
        score=score,
        chunk_index=0,
    )


def _dump(chunks: list[RetrievedChunk]) -> list[tuple]:
    """Mọi field + `repr(score)` theo đúng thứ tự — so khớp tuyệt đối, không `approx`."""
    return [
        (c.chunk_id, c.document_id, c.document_name, c.content, repr(c.score), c.chunk_index)
        for c in chunks
    ]


class _Recorder:
    """Ghi lại (args, kwargs) của từng lời gọi truy hồi và giữ dữ liệu trả về giả."""

    def __init__(self):
        self.calls: dict[str, list[tuple[tuple, dict]]] = {
            "embed_query": [],
            "dense": [],
            "graph": [],
            "merge": [],
            "retrieve": [],
            "citation": [],
        }
        self.dense_return = [_chunk("c1", "d1", 0.9)]
        self.graph_return = {"c2": (_chunk("c2", "d1", 0.4), 1.0)}
        # Cố ý KHÁC kết quả merge(): nếu node lỡ dùng retrieve() thì merged_results lộ ngay.
        self.retrieve_return = [_chunk("from-retrieve", "d1", 0.123)]
        self.citation_return = CitationGraphResult()

    def only(self, name: str) -> tuple[tuple, dict]:
        assert len(self.calls[name]) == 1, f"{name}: {len(self.calls[name])} lời gọi"
        return self.calls[name][0]


@pytest.fixture
def rec(monkeypatch) -> _Recorder:
    recorder = _Recorder()

    class _FakeEmbedder:
        def embed_query(self, *args, **kwargs):
            recorder.calls["embed_query"].append((args, kwargs))
            return EMBEDDING

    class _FakeRetriever:
        dense_weight = DENSE_WEIGHT
        graph_weight = GRAPH_WEIGHT

        def _dense_search(self, *args, **kwargs):
            recorder.calls["dense"].append((args, kwargs))
            return list(recorder.dense_return)

        def _graph_search(self, *args, **kwargs):
            recorder.calls["graph"].append((args, kwargs))
            return dict(recorder.graph_return)

        def merge(self, *args, **kwargs):
            recorder.calls["merge"].append((args, kwargs))
            # Hàm trộn THẬT (thuần, không I/O) — chỉ mượn trọng số của bản giả.
            return HybridRetriever.merge(self, *args, **kwargs)  # type: ignore[arg-type]

        def retrieve(self, *args, **kwargs):
            recorder.calls["retrieve"].append((args, kwargs))
            return list(recorder.retrieve_return)

    def _fake_graph_augmented_search(*args, **kwargs):
        recorder.calls["citation"].append((args, kwargs))
        return recorder.citation_return

    monkeypatch.setattr(retriever_module, "get_embedder", lambda: _FakeEmbedder())
    monkeypatch.setattr(retriever_module, "HybridRetriever", _FakeRetriever)
    monkeypatch.setattr(retriever_module, "graph_augmented_search", _fake_graph_augmented_search)
    return recorder


def _state(**overrides) -> dict:
    """State tối thiểu — CỐ Ý không có key `excluded_document_ids` (NotRequired)."""
    state = {
        "query": "quy định nghỉ phép",
        "rewritten_query": None,
        "document_ids": ["d1", "d2"],
        "owner_id": "user-a",
        "similarity_threshold": 0.42,
        "search_mode": "hybrid",
    }
    state.update(overrides)
    return state


class TestExcludedReachesEveryRetrievalCall:
    async def test_dense_search_receives_excluded_and_owner(self, rec):
        await retriever_node(_state(excluded_document_ids=["d9"]))

        args, kwargs = rec.only("dense")
        assert args == (EMBEDDING,)
        assert kwargs == {
            "document_ids": ["d1", "d2"],
            "owner_id": "user-a",
            "score_threshold": 0.42,
            "excluded_document_ids": ["d9"],
        }

    async def test_graph_search_receives_excluded_and_owner(self, rec):
        await retriever_node(_state(excluded_document_ids=["d9"]))

        args, kwargs = rec.only("graph")
        assert args == (["c1"],)  # seed = chunk_id của kết quả dense
        assert kwargs == {
            "document_ids": ["d1", "d2"],
            "owner_id": "user-a",
            "excluded_document_ids": ["d9"],
        }

    async def test_merge_receives_dense_list_graph_map_and_excluded(self, rec):
        """Spy trên kwargs của merge(): quên `excluded_document_ids` KHÔNG lộ ra ở đầu ra
        (`_drop_excluded` của node che mất) nên phải khẳng định ngay tại lời gọi."""
        await retriever_node(_state(excluded_document_ids=["d9"]))

        args, kwargs = rec.only("merge")
        assert kwargs == {"excluded_document_ids": ["d9"]}
        dense_arg, graph_arg = args
        assert dense_arg == rec.dense_return
        # graph_map là DICT {chunk_id: (chunk, graph_score)} của `_graph_search`,
        # không phải list `graph_results` trong state.
        assert isinstance(graph_arg, dict)
        assert graph_arg == rec.graph_return

    async def test_citation_search_receives_excluded_and_owner_in_advanced_mode(self, rec):
        await retriever_node(_state(search_mode="advanced", excluded_document_ids=["d9"]))

        args, kwargs = rec.only("citation")
        assert args == (["c1"], ["d1", "d2"], "user-a")
        assert kwargs == {"excluded_document_ids": ["d9"]}

    async def test_all_calls_in_one_run_share_the_same_exclusion(self, rec):
        # Một lượt chạy "Nâng cao": không lời gọi nào được thiếu tham số.
        await retriever_node(_state(search_mode="advanced", excluded_document_ids=["d9", "d8"]))

        for name in ("dense", "graph", "merge", "citation"):
            _, kwargs = rec.only(name)
            assert kwargs["excluded_document_ids"] == ["d9", "d8"], name

    @pytest.mark.parametrize("mode", [None, "hybrid", "keyword", "advanced", "VECTOR", ""])
    async def test_merge_gets_exclusion_in_every_hybrid_mode(self, rec, mode):
        await retriever_node(_state(search_mode=mode, excluded_document_ids=["d9"]))

        assert rec.only("merge")[1] == {"excluded_document_ids": ["d9"]}

    async def test_admin_still_passes_exclusion(self, rec):
        # owner_id=None (admin) không được làm rơi danh sách loại trừ.
        await retriever_node(
            _state(owner_id=None, search_mode="advanced", excluded_document_ids=["d9"])
        )

        for name in ("dense", "graph"):
            _, kwargs = rec.only(name)
            assert kwargs["owner_id"] is None, name
            assert kwargs["excluded_document_ids"] == ["d9"], name
        assert rec.only("merge")[1] == {"excluded_document_ids": ["d9"]}
        args, kwargs = rec.only("citation")
        assert args[2] is None
        assert kwargs == {"excluded_document_ids": ["d9"]}

    async def test_rewritten_query_run_still_passes_exclusion(self, rec):
        # Vòng rewriter → retriever dùng rewritten_query; loại trừ vẫn phải đi theo.
        await retriever_node(
            _state(rewritten_query="nghỉ phép năm bao nhiêu ngày", excluded_document_ids=["d9"])
        )

        assert rec.only("embed_query")[0] == ("nghỉ phép năm bao nhiêu ngày",)
        for name in ("dense", "graph", "merge"):
            assert rec.only(name)[1]["excluded_document_ids"] == ["d9"], name
        assert rec.calls["retrieve"] == []


class TestStateWithoutExcludedKey:
    async def test_missing_key_does_not_raise_and_passes_none(self, rec):
        state = _state(search_mode="advanced")
        assert "excluded_document_ids" not in state  # NotRequired: key vắng mặt thật

        await retriever_node(state)

        for name in ("dense", "graph", "merge", "citation"):
            _, kwargs = rec.only(name)
            assert kwargs["excluded_document_ids"] is None, name

    async def test_missing_key_keeps_other_arguments_and_owner(self, rec):
        await retriever_node(_state(search_mode="advanced"))

        assert rec.only("dense") == (
            (EMBEDDING,),
            {
                "document_ids": ["d1", "d2"],
                "owner_id": "user-a",
                "score_threshold": 0.42,
                "excluded_document_ids": None,
            },
        )
        assert rec.only("graph") == (
            (["c1"],),
            {"document_ids": ["d1", "d2"], "owner_id": "user-a", "excluded_document_ids": None},
        )
        assert rec.only("merge") == (
            (rec.dense_return, rec.graph_return),
            {"excluded_document_ids": None},
        )
        assert rec.only("citation") == (
            (["c1"], ["d1", "d2"], "user-a"),
            {"excluded_document_ids": None},
        )

    @pytest.mark.parametrize("excluded", [None, []])
    async def test_output_identical_with_missing_none_or_empty(self, rec, excluded):
        # Chunk của d9 KHÔNG bị lọc khi không có danh sách loại trừ (hành vi cũ).
        rec.dense_return = [_chunk("c1", "d1", 0.9), _chunk("c9", "d9", 0.8)]
        rec.graph_return = {"g9": (_chunk("g9", "d9", 0.3), 1.0)}

        baseline = await retriever_node(_state())
        result = await retriever_node(_state(excluded_document_ids=excluded))

        for key in ("dense_results", "graph_results", "merged_results"):
            assert result[key] == baseline[key], key
        assert [c.chunk_id for c in baseline["dense_results"]] == ["c1", "c9"]
        assert [c.chunk_id for c in baseline["graph_results"]] == ["g9"]
        assert [c.chunk_id for c in baseline["merged_results"]] == ["c1", "c9", "g9"]

    async def test_non_advanced_mode_never_calls_citation_search(self, rec):
        await retriever_node(_state(excluded_document_ids=["d9"]))
        assert rec.calls["citation"] == []


class TestNodeLevelBackstop:
    """Node gọi thẳng dense/graph nên có chốt chặn riêng: nếu filter phía DB sót thì
    chunk của tài liệu bị loại vẫn không vào state."""

    async def test_leaked_chunks_are_dropped_from_every_result_list(self, rec):
        rec.dense_return = [_chunk("c1", "d1", 0.9), _chunk("c9", "d9", 0.8)]
        rec.graph_return = {
            "g1": (_chunk("g1", "d1", 0.3), 1.0),
            "g9": (_chunk("g9", "d9", 0.3), 0.5),
        }
        rec.citation_return = CitationGraphResult(
            context_chunks=[_chunk("p1", "d1", 0.7), _chunk("p9", "d9", 0.95)]
        )

        result = await retriever_node(_state(search_mode="advanced", excluded_document_ids=["d9"]))

        assert [c.chunk_id for c in result["dense_results"]] == ["c1"]
        assert [c.chunk_id for c in result["graph_results"]] == ["g1"]
        # c1 = 0.7 (dense đứng đầu), p1 = 0.7 (Provision), g1 = 0.3 (chỉ ở graph).
        assert [c.chunk_id for c in result["merged_results"]] == ["c1", "p1", "g1"]
        for key in ("dense_results", "graph_results", "merged_results"):
            assert all(c.document_id != "d9" for c in result[key]), key

    async def test_leaked_dense_chunk_is_not_used_as_seed(self, rec):
        rec.dense_return = [_chunk("c1", "d1", 0.9), _chunk("c9", "d9", 0.8)]

        await retriever_node(_state(search_mode="advanced", excluded_document_ids=["d9"]))

        assert rec.only("graph")[0] == (["c1"],)
        assert rec.only("citation")[0][0] == ["c1"]

    async def test_only_excluded_dense_hits_skip_citation_search(self, rec):
        rec.dense_return = [_chunk("c9", "d9", 0.8)]

        result = await retriever_node(_state(search_mode="advanced", excluded_document_ids=["d9"]))

        assert result["dense_results"] == []
        assert result["merged_results"] == []
        assert rec.calls["citation"] == []

    async def test_merge_only_sees_dense_chunks_that_passed_the_backstop(self, rec):
        """Quyết định T24: trộn trên dense ĐÃ lọc. Chunk của tài liệu tắt lọt filter
        Qdrant không được vào merge() — kể cả để làm mẫu số chuẩn hoá."""
        rec.dense_return = [_chunk("x", "d9", 0.95), _chunk("a", "d1", 0.9)]
        rec.graph_return = {}

        result = await retriever_node(_state(excluded_document_ids=["d9"]))

        dense_arg, _ = rec.only("merge")[0]
        assert [c.chunk_id for c in dense_arg] == ["a"]
        # Mẫu số = 0.9 (điểm lớn nhất còn được phép), không phải 0.95 của chunk bị loại.
        assert [(c.chunk_id, c.score) for c in result["merged_results"]] == [("a", DENSE_WEIGHT)]

    async def test_merged_backstop_holds_even_if_merge_ignores_exclusion(self, rec, monkeypatch):
        """`_drop_excluded` sau khi trộn là chốt chặn cuối: merge() có bỏ sót chunk chỉ-ở-graph
        của tài liệu bị loại thì nó vẫn không vào merged_results."""
        rec.graph_return = {"g9": (_chunk("g9", "d9", 0.3), 1.0)}

        def _merge_without_exclusion(self, dense, graph, **_kwargs):
            return HybridRetriever.merge(self, dense, graph)

        monkeypatch.setattr(retriever_module.HybridRetriever, "merge", _merge_without_exclusion)

        result = await retriever_node(_state(excluded_document_ids=["d9"]))

        assert [c.chunk_id for c in result["merged_results"]] == ["c1"]


class TestSingleRetrievalPassPerRun:
    """T24: một lượt node = 1 `_dense_search` + 1 `_graph_search` + 1 `merge()`;
    `retrieve()` (chạy lại cả hai lượt tìm kiếm) không còn được gọi."""

    @pytest.mark.parametrize("mode", [None, "hybrid", "keyword", "advanced", "VECTOR", "xyz"])
    async def test_one_dense_one_graph_one_merge_and_no_retrieve(self, rec, mode):
        rec.dense_return = [_chunk("c1", "d1", 0.9), _chunk("c3", "d2", 0.45)]
        rec.graph_return = {
            "c3": (_chunk("c3", "d2", 1.0), 1.0),
            "g1": (_chunk("g1", "d1", 0.5), 0.5),
        }

        result = await retriever_node(_state(search_mode=mode))

        assert len(rec.calls["dense"]) == 1
        assert len(rec.calls["graph"]) == 1
        assert len(rec.calls["merge"]) == 1
        assert rec.calls["retrieve"] == []
        expected = HybridRetriever.merge(
            _Weights(),  # type: ignore[arg-type]
            rec.dense_return,
            rec.graph_return,
        )
        assert _dump(result["merged_results"]) == _dump(expected)
        # c1: 0.7*1 = 0.7 | c3: 0.7*0.5 + 0.3*1 = 0.65 | g1 (chỉ ở graph): 0.3*0.5 = 0.15
        assert [(c.chunk_id, c.score) for c in result["merged_results"]] == [
            ("c1", pytest.approx(0.7)),
            ("c3", pytest.approx(0.65)),
            ("g1", pytest.approx(0.15)),
        ]

    async def test_missing_search_mode_key_is_single_pass_hybrid(self, rec):
        state = _state()
        del state["search_mode"]

        await retriever_node(state)

        assert [len(rec.calls[n]) for n in ("dense", "graph", "merge", "retrieve")] == [1, 1, 1, 0]

    async def test_vector_mode_calls_neither_graph_nor_merge_nor_retrieve(self, rec):
        result = await retriever_node(_state(search_mode="vector", excluded_document_ids=["d9"]))

        assert len(rec.calls["dense"]) == 1
        assert rec.calls["graph"] == []
        assert rec.calls["merge"] == []
        assert rec.calls["retrieve"] == []
        # Nhánh vector của T22 không đổi: cosine thô, không chuẩn hoá.
        assert [(c.chunk_id, c.score) for c in result["merged_results"]] == [("c1", 0.9)]
        assert result["graph_results"] == []

    async def test_empty_dense_skips_nothing_else_and_gives_empty_merged(self, rec):
        rec.dense_return = []

        result = await retriever_node(_state(search_mode="advanced"))

        assert rec.only("graph")[0] == ([],)  # `_graph_search` thật trả {} ngay khi seed rỗng
        assert rec.calls["retrieve"] == []
        assert result["merged_results"] == []
        assert rec.calls["citation"] == []

    async def test_state_lists_keep_raw_scores_and_do_not_alias_merged(self, rec):
        """merge() trả bản sao: `dense_results` / `graph_results` trong state giữ điểm thô
        dù giờ chúng là CHÍNH đầu vào của merge() (trước T24 merged đến từ lượt tìm riêng)."""
        rec.dense_return = [_chunk("c1", "d1", 0.9), _chunk("c3", "d2", 0.45)]
        rec.graph_return = {"c3": (_chunk("c3", "d2", 1.0), 1.0)}

        result = await retriever_node(_state())

        assert [(c.chunk_id, c.score) for c in result["dense_results"]] == [
            ("c1", 0.9),
            ("c3", 0.45),
        ]
        assert [(c.chunk_id, c.score) for c in result["graph_results"]] == [("c3", 1.0)]
        source_ids = {id(c) for c in result["dense_results"] + result["graph_results"]}
        assert all(id(c) not in source_ids for c in result["merged_results"])

    async def test_advanced_dedupes_citation_chunks_against_merge_output(self, rec):
        rec.dense_return = [_chunk("c1", "d1", 0.9), _chunk("c3", "d2", 0.45)]
        rec.graph_return = {"g1": (_chunk("g1", "d1", 0.5), 0.5)}
        rec.citation_return = CitationGraphResult(
            context_chunks=[
                _chunk("c3", "d2", 0.8),  # cao hơn điểm hybrid 0.35 → thay
                _chunk("c1", "d1", 0.2),  # thấp hơn 0.7 → giữ điểm hybrid
                _chunk("p1", "d1", 0.5),
            ]
        )

        result = await retriever_node(_state(search_mode="advanced"))

        assert [(c.chunk_id, c.score) for c in result["merged_results"]] == [
            ("c3", 0.8),
            ("c1", pytest.approx(0.7)),
            ("p1", 0.5),
            ("g1", pytest.approx(0.15)),
        ]
        assert rec.calls["retrieve"] == []


class TestStatePassthrough:
    async def test_excluded_list_survives_in_returned_state(self, rec):
        # Vòng lặp rewriter → retriever đọc lại state; danh sách không được rơi mất.
        result = await retriever_node(_state(excluded_document_ids=["d9"]))
        assert result["excluded_document_ids"] == ["d9"]
        assert result["owner_id"] == "user-a"

    async def test_missing_key_is_not_invented_in_returned_state(self, rec):
        result = await retriever_node(_state())
        assert "excluded_document_ids" not in result

    async def test_returned_state_keys_are_unchanged(self, rec):
        state = _state()

        result = await retriever_node(state)

        assert set(result) == set(state) | {
            "dense_results",
            "graph_results",
            "merged_results",
            "citation_graph_path",
            "citation_graph_nodes",
            "suggested_documents",
        }


# ── HybridRetriever THẬT, Qdrant (httpx) + Neo4j driver giả ───────────────────


class _Infra:
    """Kho giả cho Qdrant và Neo4j, có đếm lời gọi.

    `apply_filters=True`  → backend lọc đúng như DB thật (trường hợp thường).
    `apply_filters=False` → backend BỎ QUA mọi filter (giả lập payload/node lệch dữ liệu).
    """

    def __init__(self):
        self.points: list[dict] = []  # id, doc, owner, score
        self.related: list[dict] = []  # chunk_id, doc, owner, seeds
        self.apply_filters = True
        self.neo4j_down = False
        self.qdrant_calls = 0
        self.neo4j_driver_requests = 0
        self.cypher_runs = 0
        self.qdrant_payloads: list[dict] = []
        self.chunk_cypher_params: list[dict] = []

    def counts(self) -> tuple[int, int, int]:
        return (self.qdrant_calls, self.neo4j_driver_requests, self.cypher_runs)

    def reset_counts(self) -> None:
        self.qdrant_calls = self.neo4j_driver_requests = self.cypher_runs = 0

    # Qdrant
    def search(self, payload: dict) -> list[dict]:
        self.qdrant_calls += 1
        self.qdrant_payloads.append(payload)
        flt = payload.get("filter") or {}
        threshold = payload.get("score_threshold")
        hits = []
        for p in self.points:
            if self.apply_filters:
                must = {c["key"]: c["match"] for c in flt.get("must", [])}
                if "document_id" in must and p["doc"] not in must["document_id"]["any"]:
                    continue
                if "owner_id" in must and p["owner"] != must["owner_id"]["value"]:
                    continue
                if any(p["doc"] in c["match"]["any"] for c in flt.get("must_not", [])):
                    continue
                if threshold is not None and p["score"] < threshold:
                    continue
            hits.append(p)
        hits.sort(key=lambda p: p["score"], reverse=True)
        return [
            {
                "id": p["id"],
                "score": p["score"],
                "payload": {
                    "document_id": p["doc"],
                    "document_name": f"{p['doc']}.pdf",
                    "content": f"content of {p['id']}",
                    "chunk_index": 1,
                },
            }
            for p in hits[: payload["limit"]]
        ]

    # Neo4j
    def run(self, query: str, params: dict) -> list[dict]:
        self.cypher_runs += 1
        if "NEXT_CHUNK|REFERENCES" not in query:
            return []  # truy vấn Provision của graph_augmented_search → không có gì
        self.chunk_cypher_params.append(params)
        seeds = set(params["seed_ids"])
        rows = []
        for r in self.related:
            connections = len(seeds & set(r["seeds"]))
            if r["chunk_id"] in seeds or not connections:
                continue
            if self.apply_filters:
                if params["document_ids"] and r["doc"] not in params["document_ids"]:
                    continue
                if params["owner_id"] is not None and r["owner"] != params["owner_id"]:
                    continue
                if r["doc"] in params["excluded_document_ids"]:
                    continue
            rows.append(
                {
                    "chunk_id": r["chunk_id"],
                    "document_id": r["doc"],
                    "document_name": f"{r['doc']}.pdf",
                    "content": f"graph content of {r['chunk_id']}",
                    "chunk_index": 2,
                    "connections": connections,
                }
            )
        rows.sort(key=lambda row: row["connections"], reverse=True)
        return rows[: params["limit"]]


def _default_points() -> list[dict]:
    return [
        {"id": "a1", "doc": "d1", "owner": "user-a", "score": 0.82},
        {"id": "a2", "doc": "d2", "owner": "user-a", "score": 0.61},
        {"id": "a3", "doc": "d1", "owner": "user-a", "score": 0.47},
        {"id": "a9", "doc": "d9", "owner": "user-a", "score": 0.93},  # tài liệu sẽ bị tắt
        {"id": "b1", "doc": "d1", "owner": "user-b", "score": 0.99},  # của người khác
    ]


def _default_related() -> list[dict]:
    return [
        {"chunk_id": "g1", "doc": "d1", "owner": "user-a", "seeds": ["a1", "a2", "a3"]},
        {"chunk_id": "g2", "doc": "d2", "owner": "user-a", "seeds": ["a1"]},
        {"chunk_id": "g9", "doc": "d9", "owner": "user-a", "seeds": ["a1", "a2"]},
        {"chunk_id": "gb", "doc": "d1", "owner": "user-b", "seeds": ["a1", "a2", "a3"]},
        # Chunk dense a3 cũng là hàng xóm trên graph của a1 (khi a3 không làm seed).
        {"chunk_id": "a3", "doc": "d1", "owner": "user-a", "seeds": ["a1"]},
    ]


@pytest.fixture
def infra(monkeypatch) -> _Infra:
    """HybridRetriever THẬT; chỉ thay tầng mạng (httpx cho Qdrant, driver cho Neo4j)."""
    state = _Infra()
    state.points = _default_points()
    state.related = _default_related()

    class _FakeResponse:
        status_code = 200

        def __init__(self, hits):
            self._hits = hits

        def json(self):
            return {"result": self._hits}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json, headers):  # noqa: A002 - match httpx signature
            return _FakeResponse(state.search(json))

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def data(self):
            return self._rows

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def run(self, query, **params):
            return _FakeResult(state.run(query, params))

    class _FakeDriver:
        @staticmethod
        def session():
            return _FakeSession()

    def _get_driver():
        state.neo4j_driver_requests += 1
        if state.neo4j_down:
            raise ConnectionError("neo4j down (test)")
        return _FakeDriver()

    class _FakeEmbedder:
        def embed_query(self, query):
            return EMBEDDING

    import httpx

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    monkeypatch.setattr(rag_retriever_module, "get_qdrant_client", lambda: None)
    monkeypatch.setattr(graph_client, "get_neo4j_driver", _get_driver)
    monkeypatch.setattr(retriever_module, "get_embedder", lambda: _FakeEmbedder())
    return state


def _real_state(**overrides) -> dict:
    state = {
        "query": "quy định nghỉ phép",
        "rewritten_query": None,
        "document_ids": None,
        "owner_id": "user-a",
        "similarity_threshold": None,
        "search_mode": "hybrid",
    }
    state.update(overrides)
    return state


def _retrieve_like_before_t24(state: dict) -> list[RetrievedChunk]:
    """Đường node dùng TRƯỚC T24: `HybridRetriever.retrieve()` với đúng tham số cũ."""
    return HybridRetriever().retrieve(
        state.get("rewritten_query") or state["query"],
        EMBEDDING,
        document_ids=state.get("document_ids"),
        owner_id=state.get("owner_id"),
        score_threshold=state.get("similarity_threshold"),
        excluded_document_ids=state.get("excluded_document_ids"),
    )


HYBRID_MODES = [None, "hybrid", "keyword"]


class TestBackendCallCounts:
    """Đếm lời gọi mạng thật sự rời khỏi HybridRetriever — bắt cả đường GIÁN TIẾP
    (vd ai đó gọi lại `retrieve()` trong node) mà spy trên bản giả không thấy."""

    @pytest.mark.parametrize("mode", HYBRID_MODES)
    async def test_hybrid_is_one_qdrant_and_one_neo4j_call_per_run(self, infra, mode):
        result = await retriever_node(_real_state(search_mode=mode))

        # Trước T24: (2, 2, 2) — `retrieve()` chạy lại cả dense lẫn graph.
        assert infra.counts() == (1, 1, 1)
        assert result["merged_results"]  # có kết quả thật, không phải đếm trên lượt rỗng
        assert result["graph_results"]

    async def test_missing_search_mode_key_is_one_and_one(self, infra):
        state = _real_state()
        del state["search_mode"]

        await retriever_node(state)

        assert infra.counts() == (1, 1, 1)

    async def test_advanced_adds_only_the_citation_graph_call(self, infra):
        await retriever_node(_real_state(search_mode="advanced"))

        # 1 Qdrant; Neo4j: 1 `_graph_search` + 1 `graph_augmented_search` (trước T24: 2 + 3).
        assert infra.counts() == (1, 2, 2)

    async def test_vector_is_one_qdrant_and_zero_neo4j(self, infra):
        await retriever_node(_real_state(search_mode="vector"))

        assert infra.counts() == (1, 0, 0)

    @pytest.mark.parametrize(
        ("mode", "per_run"),
        [("hybrid", (1, 1, 1)), ("advanced", (1, 2, 2)), ("vector", (1, 0, 0))],
    )
    async def test_counts_scale_linearly_over_rewriter_retries(self, infra, mode, per_run):
        # MAX_RETRIES = 2 → tối đa 3 lượt node cho một câu hỏi.
        for attempt in range(3):
            await retriever_node(
                _real_state(search_mode=mode, rewritten_query=f"viết lại {attempt}")
            )

        assert infra.counts() == tuple(3 * n for n in per_run)

    async def test_no_dense_hits_means_no_neo4j_call_at_all(self, infra):
        infra.points = []

        result = await retriever_node(_real_state(search_mode="advanced"))

        assert infra.counts() == (1, 0, 0)
        assert result["merged_results"] == []

    async def test_single_calls_still_carry_every_security_filter(self, infra):
        await retriever_node(
            _real_state(
                document_ids=["d1", "d2", "d9"],
                similarity_threshold=0.42,
                excluded_document_ids=["d9"],
            )
        )

        (payload,) = infra.qdrant_payloads
        assert payload["filter"] == {
            "must": [
                {"key": "document_id", "match": {"any": ["d1", "d2", "d9"]}},
                {"key": "owner_id", "match": {"value": "user-a"}},
            ],
            "must_not": [{"key": "document_id", "match": {"any": ["d9"]}}],
        }
        assert payload["score_threshold"] == 0.42
        (params,) = infra.chunk_cypher_params
        assert params["seed_ids"] == ["a1", "a2", "a3"]
        assert params["document_ids"] == ["d1", "d2", "d9"]
        assert params["owner_id"] == "user-a"
        assert params["excluded_document_ids"] == ["d9"]

    async def test_real_merge_receives_exclusion_and_retrieve_is_never_called(
        self, infra, monkeypatch
    ):
        merge_calls: list[tuple[tuple, dict]] = []
        real_merge = HybridRetriever.merge

        def _spy_merge(self, *args, **kwargs):
            merge_calls.append((args, kwargs))
            return real_merge(self, *args, **kwargs)

        def _retrieve_must_not_run(self, *args, **kwargs):
            raise AssertionError("retriever_node không được gọi retrieve()")

        monkeypatch.setattr(HybridRetriever, "merge", _spy_merge)
        monkeypatch.setattr(HybridRetriever, "retrieve", _retrieve_must_not_run)

        result = await retriever_node(_real_state(excluded_document_ids=["d9", "d8"]))

        ((args, kwargs),) = merge_calls
        assert kwargs == {"excluded_document_ids": ["d9", "d8"]}
        assert [c.chunk_id for c in args[0]] == ["a1", "a2", "a3"]
        assert isinstance(args[1], dict)
        assert set(args[1]) == {"g1", "g2"}
        assert result["merged_results"]


class TestSameResultsAsRetrieve:
    """Bộ lọc phía DB hoạt động đúng (trường hợp thường) → `merged_results` sau T24 bằng
    TUYỆT ĐỐI kết quả `retrieve()` mà node dùng trước T24: id, từng điểm số, thứ tự."""

    @pytest.mark.parametrize("mode", HYBRID_MODES)
    @pytest.mark.parametrize("excluded", ["missing", None, [], ["d9"], ["d9", "d2"]])
    @pytest.mark.parametrize("owner_id", ["user-a", None])
    async def test_merged_equals_retrieve_output(self, infra, mode, excluded, owner_id):
        state = _real_state(search_mode=mode, owner_id=owner_id)
        if excluded != "missing":
            state["excluded_document_ids"] = excluded

        result = await retriever_node(state)
        expected = _retrieve_like_before_t24(state)

        assert expected  # đối chứng: không so hai danh sách rỗng
        assert _dump(result["merged_results"]) == _dump(expected)

    async def test_default_dataset_scores_are_the_hybrid_formula(self, infra):
        """Khoá số cụ thể để phép so với `retrieve()` ở trên không thành vòng tròn."""
        result = await retriever_node(_real_state(excluded_document_ids=["d9"]))

        # dense (đã loại d9): a1 0.82, a2 0.61, a3 0.47 → max 0.82
        # graph: g1 nối 3 seed (1.0), g2 nối 1 seed (1/3); a3 là seed nên không tính.
        assert [(c.chunk_id, c.score) for c in result["merged_results"]] == [
            ("a1", pytest.approx(0.7)),
            ("a2", pytest.approx(0.7 * 0.61 / 0.82)),
            ("a3", pytest.approx(0.7 * 0.47 / 0.82)),
            ("g1", pytest.approx(0.3)),
            ("g2", pytest.approx(0.1)),
        ]
        assert [c.chunk_id for c in result["dense_results"]] == ["a1", "a2", "a3"]
        assert [c.chunk_id for c in result["graph_results"]] == ["g1", "g2"]

    async def test_dense_chunk_boosted_by_graph_matches_retrieve(self, infra):
        """Chunk vừa ở dense vừa ở graph: ngưỡng tương đồng loại a3 khỏi dense nên a3 trở
        thành hàng xóm graph của a1 (chỉ-ở-graph), còn a2/a1 vẫn khớp `retrieve()`."""
        state = _real_state(similarity_threshold=0.5, excluded_document_ids=["d9"])

        result = await retriever_node(state)

        assert [c.chunk_id for c in result["dense_results"]] == ["a1", "a2"]
        assert {c.chunk_id for c in result["graph_results"]} == {"g1", "g2", "a3"}
        assert _dump(result["merged_results"]) == _dump(_retrieve_like_before_t24(state))

    async def test_advanced_with_empty_citation_graph_equals_retrieve(self, infra):
        state = _real_state(search_mode="advanced", excluded_document_ids=["d9"])

        result = await retriever_node(state)

        assert _dump(result["merged_results"]) == _dump(_retrieve_like_before_t24(state))
        assert result["citation_graph_path"] == []

    async def test_advanced_dedupe_runs_on_the_same_list_as_before(self, infra, monkeypatch):
        citation_chunks = [
            _chunk("a2", "d2", 0.95),
            _chunk("a1", "d1", 0.1),
            _chunk("p1", "d1", 0.5),
        ]
        monkeypatch.setattr(
            retriever_module,
            "graph_augmented_search",
            lambda *a, **k: CitationGraphResult(context_chunks=list(citation_chunks)),
        )
        state = _real_state(search_mode="advanced", excluded_document_ids=["d9"])

        result = await retriever_node(state)

        # Oracle: dedupe "giữ điểm cao hơn" áp lên kết quả `retrieve()` (đầu vào trước T24).
        combined = {c.chunk_id: c for c in _retrieve_like_before_t24(state)}
        for chunk in citation_chunks:
            if chunk.chunk_id not in combined or chunk.score > combined[chunk.chunk_id].score:
                combined[chunk.chunk_id] = chunk
        expected = sorted(combined.values(), key=lambda c: c.score, reverse=True)
        assert _dump(result["merged_results"]) == _dump(expected)
        assert [c.chunk_id for c in result["merged_results"]][:2] == ["a2", "a1"]

    async def test_random_datasets_match_retrieve_in_every_hybrid_mode(self, infra):
        rng = random.Random(24)
        docs = ["d1", "d2", "d3", "d9"]
        owners = ["user-a", "user-b"]
        compared = 0
        for _ in range(60):
            infra.points = [
                {
                    "id": f"c{i}",
                    "doc": rng.choice(docs),
                    "owner": rng.choice(owners),
                    # Điểm trùng nhau và điểm 0 để chạm nhánh hoà / `max_dense or 1.0`.
                    "score": rng.choice([round(rng.uniform(0.05, 0.99), 4), 0.5, 0.0]),
                }
                for i in range(rng.randint(0, 12))
            ]
            ids = [p["id"] for p in infra.points]
            infra.related = [
                {
                    "chunk_id": rng.choice(ids) if ids and rng.random() < 0.3 else f"g{i}",
                    "doc": rng.choice(docs),
                    "owner": rng.choice(owners),
                    "seeds": rng.sample(ids, rng.randint(0, len(ids))),
                }
                for i in range(rng.randint(0, 10))
            ]
            state = _real_state(
                search_mode=rng.choice([None, "hybrid", "keyword", "advanced"]),
                owner_id=rng.choice([None, "user-a", "user-b"]),
                document_ids=rng.choice([None, ["d1", "d2"], ["d1", "d2", "d9"]]),
                similarity_threshold=rng.choice([None, 0.3, 0.6]),
                excluded_document_ids=rng.choice([None, [], ["d9"], ["d9", "d3"]]),
            )

            result = await retriever_node(state)
            expected = _retrieve_like_before_t24(state)

            assert _dump(result["merged_results"]) == _dump(expected), state
            compared += len(expected)
        assert compared > 100  # đối chứng: phần lớn ca có kết quả thật

    async def test_vector_branch_is_untouched_raw_cosine(self, infra):
        result = await retriever_node(
            _real_state(search_mode="vector", excluded_document_ids=["d9"])
        )

        assert [(c.chunk_id, c.score) for c in result["merged_results"]] == [
            ("a1", 0.82),
            ("a2", 0.61),
            ("a3", 0.47),
        ]
        assert result["graph_results"] == []


class TestNormalisationWhenDbFilterLeaks:
    """Khác biệt CÓ CHỦ Ý với `retrieve()`: node lọc dense (`_drop_excluded`) TRƯỚC khi
    trộn, nên khi filter Qdrant sót, chunk của tài liệu tắt không còn làm mẫu số chuẩn hoá.
    Chỉ xảy ra khi backend bỏ sót filter; không rò rỉ ở cả hai cách, chỉ khác thang điểm."""

    async def test_leaked_inactive_chunk_does_not_scale_down_allowed_scores(self, infra):
        infra.apply_filters = False  # Qdrant/Neo4j bỏ qua mọi filter
        infra.points = [
            {"id": "x", "doc": "d9", "owner": "user-a", "score": 0.95},
            {"id": "a", "doc": "d1", "owner": "user-a", "score": 0.9},
        ]
        infra.related = []
        state = _real_state(excluded_document_ids=["d9"])

        result = await retriever_node(state)

        assert [(c.chunk_id, c.score) for c in result["merged_results"]] == [("a", 0.7)]
        # Đối chứng — `retrieve()` (trước T24) chuẩn hoá trên cả chunk bị loại: 0.7 * 0.9 / 0.95.
        (old,) = _retrieve_like_before_t24(state)
        assert (old.chunk_id, old.score) == ("a", pytest.approx(0.6631578947368421))

    async def test_nothing_from_inactive_document_leaks_when_db_ignores_filters(self, infra):
        infra.apply_filters = False
        state = _real_state(search_mode="advanced", excluded_document_ids=["d9"])

        result = await retriever_node(state)

        for key in ("dense_results", "graph_results", "merged_results"):
            assert result[key], key
            assert all(c.document_id != "d9" for c in result[key]), key
        # a9 (d9) không được làm seed cho graph.
        assert "a9" not in infra.chunk_cypher_params[0]["seed_ids"]
        assert infra.counts() == (1, 2, 2)

    async def test_leak_changes_scores_only_not_membership_or_order(self, infra):
        infra.apply_filters = False
        state = _real_state(excluded_document_ids=["d9"], owner_id=None)

        result = await retriever_node(state)
        old = _retrieve_like_before_t24(state)

        assert [c.chunk_id for c in result["merged_results"] if c.document_id != "d9"]
        dense_ids = {c.chunk_id for c in result["dense_results"]}
        new_dense_order = [c.chunk_id for c in result["merged_results"] if c.chunk_id in dense_ids]
        old_dense_order = [c.chunk_id for c in old if c.chunk_id in dense_ids]
        assert new_dense_order == old_dense_order
        assert {c.chunk_id for c in result["merged_results"]} >= dense_ids


class TestNeo4jDownLogsOnce:
    """Review T13: trước T24 mỗi request ghi HAI WARNING (+ hai traceback) khi Neo4j chết,
    vì `_graph_search` chạy hai lần. Giờ chỉ còn một."""

    @staticmethod
    def _graph_warnings(caplog) -> list[logging.LogRecord]:
        return [
            r
            for r in caplog.records
            if r.name == "app.rag.retriever" and r.levelno == logging.WARNING
        ]

    @pytest.mark.parametrize("mode", [None, "hybrid", "keyword", "advanced"])
    async def test_one_warning_per_run_and_dense_only_fallback(self, infra, caplog, mode):
        infra.neo4j_down = True
        caplog.set_level(logging.WARNING)

        result = await retriever_node(_real_state(search_mode=mode, excluded_document_ids=["d9"]))

        warnings = self._graph_warnings(caplog)
        assert len(warnings) == 1
        assert "falling back to dense-only" in warnings[0].getMessage()
        assert infra.qdrant_calls == 1
        # Rơi về dense-only: vẫn có kết quả, điểm = 0.7 * chuẩn hoá, không có phần graph.
        assert result["graph_results"] == []
        assert [(c.chunk_id, c.score) for c in result["merged_results"]] == [
            ("a1", pytest.approx(0.7)),
            ("a2", pytest.approx(0.7 * 0.61 / 0.82)),
            ("a3", pytest.approx(0.7 * 0.47 / 0.82)),
        ]

    async def test_neo4j_down_result_equals_retrieve_fallback(self, infra):
        infra.neo4j_down = True
        state = _real_state(excluded_document_ids=["d9"])

        result = await retriever_node(state)

        assert _dump(result["merged_results"]) == _dump(_retrieve_like_before_t24(state))

    async def test_three_retries_log_three_warnings_not_six(self, infra, caplog):
        infra.neo4j_down = True
        caplog.set_level(logging.WARNING)

        for attempt in range(3):
            await retriever_node(_real_state(rewritten_query=f"viết lại {attempt}"))

        assert len(self._graph_warnings(caplog)) == 3
        assert infra.neo4j_driver_requests == 3

    async def test_vector_mode_logs_nothing_when_neo4j_is_down(self, infra, caplog):
        infra.neo4j_down = True
        caplog.set_level(logging.WARNING)

        await retriever_node(_real_state(search_mode="vector"))

        assert self._graph_warnings(caplog) == []
        assert infra.neo4j_driver_requests == 0

    async def test_healthy_neo4j_logs_no_warning(self, infra, caplog):
        caplog.set_level(logging.WARNING)

        await retriever_node(_real_state())

        assert self._graph_warnings(caplog) == []
