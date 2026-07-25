"""
graph_indexer.py — phần thuần logic (build_legal_address, build_document_address),
không cần Neo4j. Test có Neo4j thật cho index_provisions_to_graph()/
index_external_placeholders_to_graph()/index_legal_document_to_graph()/
index_document_placeholders_to_graph() nằm ở
app/tests/integration/test_provision_graph.py (marker @pytest.mark.neo4j).
"""

from app.ingestion.graph_indexer import (
    build_document_address,
    build_legal_address,
    index_document_placeholders_to_graph,
    index_external_placeholders_to_graph,
    normalize_document_code,
)


def test_build_legal_address_dieu_only():
    assert build_legal_address("u1", "99/2024/NĐ-CP", 5) == "owner_u1:99/2024/NĐ-CP:DIEU_5"


def test_build_legal_address_dieu_khoan():
    addr = build_legal_address("u1", "99/2024/NĐ-CP", 5, khoan=2)
    assert addr == "owner_u1:99/2024/NĐ-CP:DIEU_5:KHOAN_2"


def test_build_legal_address_dieu_khoan_diem():
    addr = build_legal_address("u1", "99/2024/NĐ-CP", 5, khoan=2, diem="a")
    assert addr == "owner_u1:99/2024/NĐ-CP:DIEU_5:KHOAN_2:DIEM_a"


def test_build_legal_address_diem_without_khoan_is_ignored():
    """diem chỉ được gắn vào địa chỉ nếu khoan có mặt (xem build_legal_address:
    nhánh diem nằm lồng trong nhánh if khoan is not None) — diem đứng một mình
    không có nghĩa hợp lệ trong lược đồ Điều/Khoản/Điểm."""
    addr = build_legal_address("u1", "code", 5, khoan=None, diem="a")
    assert addr == "owner_u1:CODE:DIEU_5"


def test_build_legal_address_deterministic_across_calls():
    args = ("u1", "99/2024/NĐ-CP", 5, 2, "a")
    assert build_legal_address(*args) == build_legal_address(*args)


def test_build_legal_address_none_owner_id():
    # owner_id=None có nghĩa riêng ("admin/không filter") ở các nơi khác trong
    # codebase — build_legal_address không được phép coi None là lỗi.
    assert build_legal_address(None, "code", 1) == "owner_None:CODE:DIEU_1"


def test_build_legal_address_normalizes_document_code():
    """Chuẩn hoá tối thiểu (phase 3): khoảng trắng thừa + hoa/thường không được
    tạo ra 2 địa chỉ khác nhau cho cùng 1 văn bản."""
    addr = build_legal_address("u1", "  99/2024/nđ-cp ", 5)
    assert addr == "owner_u1:99/2024/NĐ-CP:DIEU_5"
    assert addr == build_legal_address("u1", "99/2024/NĐ-CP", 5)


# ── normalize_document_code ───────────────────────────────────────────────────


def test_normalize_document_code_trims_and_uppercases():
    assert normalize_document_code("  99/2024/nđ-cp ") == "99/2024/NĐ-CP"


def test_normalize_document_code_collapses_internal_whitespace():
    assert normalize_document_code("99 /2024/ NĐ-CP") == "99/2024/NĐ-CP"


def test_normalize_document_code_idempotent():
    once = normalize_document_code("  99/2024/nđ-cp ")
    assert normalize_document_code(once) == once


def test_normalize_document_code_already_clean_is_unchanged():
    assert normalize_document_code("99/2024/NĐ-CP") == "99/2024/NĐ-CP"


# ── build_document_address ────────────────────────────────────────────────────


def test_build_document_address_basic():
    assert build_document_address("u1", "99/2024/NĐ-CP") == "owner_u1:99/2024/NĐ-CP"


def test_build_document_address_normalizes_document_code():
    addr = build_document_address("u1", "  99/2024/nđ-cp ")
    assert addr == "owner_u1:99/2024/NĐ-CP"


def test_build_document_address_none_owner_id():
    assert build_document_address(None, "code") == "owner_None:CODE"


def test_build_document_address_has_no_dieu_segment():
    """LegalDocument là điểm neo cấp văn bản — địa chỉ KHÔNG được có DIEU/KHOAN,
    khác build_legal_address (Provision)."""
    addr = build_document_address("u1", "99/2024/NĐ-CP")
    assert "DIEU" not in addr
    assert addr.count(":") == 1


def test_index_external_placeholders_to_graph_empty_citations_is_noop():
    """[] citations -> return sớm, KHÔNG chạm tới driver (an toàn gọi với
    driver=None trong test thuần logic này, không cần Neo4j thật)."""
    index_external_placeholders_to_graph(
        driver=None,  # type: ignore[arg-type]
        owner_id="u1",
        own_document_code="99/2024/NĐ-CP",
        citations=[],
    )


def test_index_document_placeholders_to_graph_empty_citations_is_noop():
    """Cùng nguyên tắc — [] citations -> return sớm, không chạm driver."""
    index_document_placeholders_to_graph(
        driver=None,  # type: ignore[arg-type]
        owner_id="u1",
        own_document_code="99/2024/NĐ-CP",
        citations=[],
    )
