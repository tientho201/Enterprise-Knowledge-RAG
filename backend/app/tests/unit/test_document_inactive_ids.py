"""`DocumentRepository.list_inactive_ids` — ID tài liệu đang tắt (`is_active=False`).

Danh sách này dùng để loại tài liệu tắt khỏi RAG, nên phải: bỏ qua doc đang bật,
bỏ qua doc đã soft-delete, và owner-scoped (user chỉ nhận doc tắt của mình; admin
`owner_id=None` nhận của mọi user). Test ở tầng repo dùng SQLite in-memory
(fixture db_session), không cần S3/Celery/Redis.
"""

from app.models.document import DocumentType
from app.repositories.document_repo import DocumentRepository

USER_A = "user-inactive-aaaa"
USER_B = "user-inactive-bbbb"


async def _seed(db):
    """Mỗi user 1 doc bật + 1 doc tắt; USER_A thêm 1 doc tắt đã soft-delete; 1 doc legacy tắt."""
    repo = DocumentRepository(db)

    async def _doc(name: str, owner_id: str | None, *, active: bool):
        doc = await repo.create(name=name, doc_type=DocumentType.pdf, owner_id=owner_id)
        if not active:
            await repo.set_active(doc.id, False)
        return doc

    docs = {
        "a_on": await _doc("a-on.pdf", USER_A, active=True),
        "a_off": await _doc("a-off.pdf", USER_A, active=False),
        "a_off_deleted": await _doc("a-off-deleted.pdf", USER_A, active=False),
        "b_on": await _doc("b-on.pdf", USER_B, active=True),
        "b_off": await _doc("b-off.pdf", USER_B, active=False),
        "legacy_off": await _doc("legacy-off.pdf", None, active=False),
    }
    assert await repo.soft_delete(docs["a_off_deleted"].id) is True
    await db.flush()
    return repo, docs


async def test_active_docs_are_not_listed(db_session):
    repo, docs = await _seed(db_session)
    ids = await repo.list_inactive_ids(USER_A)
    assert docs["a_on"].id not in ids
    assert docs["a_off"].id in ids


async def test_other_users_inactive_docs_are_not_listed(db_session):
    repo, docs = await _seed(db_session)
    ids = await repo.list_inactive_ids(USER_A)
    assert docs["b_off"].id not in ids
    assert docs["legacy_off"].id not in ids
    # chiều ngược lại: USER_B cũng không thấy doc tắt của USER_A
    assert await repo.list_inactive_ids(USER_B) == [docs["b_off"].id]


async def test_soft_deleted_inactive_docs_are_not_listed(db_session):
    repo, docs = await _seed(db_session)
    assert docs["a_off_deleted"].id not in await repo.list_inactive_ids(USER_A)
    assert docs["a_off_deleted"].id not in await repo.list_inactive_ids(None)


async def test_owner_scoped_result_is_exact(db_session):
    repo, docs = await _seed(db_session)
    assert await repo.list_inactive_ids(USER_A) == [docs["a_off"].id]


async def test_owner_none_lists_inactive_docs_of_all_users(db_session):
    repo, docs = await _seed(db_session)
    ids = await repo.list_inactive_ids(None)
    # `<=` thay vì `==`: engine SQLite dùng chung cả session test (mirror test_document_isolation)
    assert {docs["a_off"].id, docs["b_off"].id, docs["legacy_off"].id} <= set(ids)
    assert docs["a_on"].id not in ids
    assert docs["b_on"].id not in ids
    assert all(isinstance(i, str) for i in ids)


async def test_user_without_inactive_docs_gets_empty_list(db_session):
    repo, _docs = await _seed(db_session)
    assert await repo.list_inactive_ids("user-inactive-none") == []
