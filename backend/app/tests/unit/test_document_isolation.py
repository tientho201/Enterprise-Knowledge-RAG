"""Data isolation cho documents — owner-scoped (personal workspace).

Kiểm tra: user chỉ thấy/truy cập doc mình sở hữu; admin thấy tất cả; doc legacy
(owner=None) ẩn với non-admin. Test ở tầng service/repo dùng SQLite in-memory
(fixture db_session), không cần S3/Celery/Redis.
"""

import pytest
from fastapi import HTTPException

from app.models.document import DocumentType
from app.services.document_service import DocumentService

USER_A = "user-aaaa"
USER_B = "user-bbbb"


async def _seed(db):
    svc = DocumentService(db)
    doc_a = await svc.repo.create(name="a.pdf", doc_type=DocumentType.pdf, owner_id=USER_A)
    doc_b = await svc.repo.create(name="b.pdf", doc_type=DocumentType.pdf, owner_id=USER_B)
    doc_legacy = await svc.repo.create(name="old.pdf", doc_type=DocumentType.pdf, owner_id=None)
    await db.flush()
    return svc, doc_a, doc_b, doc_legacy


async def test_list_documents_scoped_to_owner(db_session):
    svc, doc_a, _doc_b, _legacy = await _seed(db_session)
    res = await svc.list_documents(user_id=USER_A, is_admin=False)
    ids = {d.id for d in res.items}
    assert ids == {doc_a.id}
    assert res.total == 1


async def test_admin_sees_all_documents(db_session):
    svc, doc_a, doc_b, legacy = await _seed(db_session)
    res = await svc.list_documents(user_id="user-admin", is_admin=True)
    ids = {d.id for d in res.items}
    assert {doc_a.id, doc_b.id, legacy.id} <= ids


async def test_get_other_users_doc_raises_404(db_session):
    svc, _doc_a, doc_b, _legacy = await _seed(db_session)
    with pytest.raises(HTTPException) as exc:
        await svc.get(doc_b.id, user_id=USER_A, is_admin=False)
    assert exc.value.status_code == 404


async def test_admin_can_get_any_doc(db_session):
    svc, _doc_a, doc_b, _legacy = await _seed(db_session)
    got = await svc.get(doc_b.id, user_id="user-admin", is_admin=True)
    assert got.id == doc_b.id


async def test_legacy_null_owner_hidden_from_non_admin(db_session):
    svc, _doc_a, _doc_b, legacy = await _seed(db_session)
    with pytest.raises(HTTPException) as exc:
        await svc.get(legacy.id, user_id=USER_A, is_admin=False)
    assert exc.value.status_code == 404
    # nhưng admin vẫn truy cập được
    assert (await svc.get(legacy.id, user_id="admin", is_admin=True)).id == legacy.id
