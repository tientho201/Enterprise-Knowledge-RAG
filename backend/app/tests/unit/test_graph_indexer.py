"""
graph_indexer.py — phần thuần logic (build_legal_address), không cần Neo4j.
Test có Neo4j thật cho index_provisions_to_graph()/
index_external_placeholders_to_graph() (placeholder — phase 2) nằm ở
app/tests/integration/test_provision_graph.py (marker @pytest.mark.neo4j).
"""

from app.ingestion.graph_indexer import build_legal_address, index_external_placeholders_to_graph


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
    assert addr == "owner_u1:code:DIEU_5"


def test_build_legal_address_deterministic_across_calls():
    args = ("u1", "99/2024/NĐ-CP", 5, 2, "a")
    assert build_legal_address(*args) == build_legal_address(*args)


def test_build_legal_address_none_owner_id():
    # owner_id=None có nghĩa riêng ("admin/không filter") ở các nơi khác trong
    # codebase — build_legal_address không được phép coi None là lỗi.
    assert build_legal_address(None, "code", 1) == "owner_None:code:DIEU_1"


def test_index_external_placeholders_to_graph_empty_citations_is_noop():
    """[] citations -> return sớm, KHÔNG chạm tới driver (an toàn gọi với
    driver=None trong test thuần logic này, không cần Neo4j thật)."""
    index_external_placeholders_to_graph(
        driver=None,  # type: ignore[arg-type]
        owner_id="u1",
        own_document_code="99/2024/NĐ-CP",
        citations=[],
    )
