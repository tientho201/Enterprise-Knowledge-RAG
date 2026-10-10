"""`ConversationRepository.list_recent_messages` — N tin nhắn gần nhất của một hội thoại.

Kết quả sẽ đi vào prompt LLM (lịch sử hội thoại), nên phải: đúng `limit` tin nhắn
CUỐI, trả theo thứ tự cũ -> mới, thứ tự xác định khi trùng `created_at`, và cô lập
theo chủ hội thoại (user khác gọi cùng `conversation_id` nhận `[]`). Test ở tầng repo
dùng SQLite in-memory (fixture db_session), không cần S3/Celery/Redis.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import event
from sqlalchemy.orm.attributes import instance_state

from app.models.message import Message, MessageRole
from app.repositories.conversation_repo import ConversationRepository

USER_A = "user-recent-aaaa"
USER_B = "user-recent-bbbb"
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


async def _msg(db, conv_id: str, role: MessageRole, content: str, *, at: datetime, id_=None):
    """Ghi thẳng `Message` để tự đặt `created_at` (repo.add_message dùng giờ hiện tại)."""
    msg = Message(conversation_id=conv_id, role=role, content=content, created_at=at)
    if id_ is not None:
        msg.id = id_
    db.add(msg)
    await db.flush()
    return msg


async def _seed_conversation(db, user_id: str, n_turns: int, *, prefix: str = "m"):
    """Hội thoại `n_turns` lượt (user rồi assistant), mỗi tin nhắn cách nhau 1 giây."""
    repo = ConversationRepository(db)
    conv = await repo.create(user_id=user_id, title=f"{prefix}-conv")
    for i in range(n_turns):
        await _msg(
            db, conv.id, MessageRole.user, f"{prefix}-q{i}", at=T0 + timedelta(seconds=2 * i)
        )
        await _msg(
            db,
            conv.id,
            MessageRole.assistant,
            f"{prefix}-a{i}",
            at=T0 + timedelta(seconds=2 * i + 1),
        )
    return repo, conv


def _contents(messages: list[Message]) -> list[str]:
    return [m.content for m in messages]


async def test_returns_last_n_messages_oldest_first(db_session):
    repo, conv = await _seed_conversation(db_session, USER_A, 4)
    messages = await repo.list_recent_messages(conv.id, USER_A, 3)
    assert _contents(messages) == ["m-a2", "m-q3", "m-a3"]
    assert [m.role for m in messages] == [
        MessageRole.assistant,
        MessageRole.user,
        MessageRole.assistant,
    ]
    assert all(isinstance(m, Message) for m in messages)


async def test_limit_larger_than_history_returns_everything_in_order(db_session):
    repo, conv = await _seed_conversation(db_session, USER_A, 2)
    messages = await repo.list_recent_messages(conv.id, USER_A, 50)
    assert _contents(messages) == ["m-q0", "m-a0", "m-q1", "m-a1"]


async def test_limit_one_returns_only_newest(db_session):
    repo, conv = await _seed_conversation(db_session, USER_A, 3)
    assert _contents(await repo.list_recent_messages(conv.id, USER_A, 1)) == ["m-a2"]


async def test_insert_order_does_not_matter_only_created_at(db_session):
    """Ghi lộn xộn: thứ tự trả về theo `created_at`, không theo thứ tự INSERT."""
    repo = ConversationRepository(db_session)
    conv = await repo.create(user_id=USER_A)
    await _msg(db_session, conv.id, MessageRole.assistant, "third", at=T0 + timedelta(seconds=3))
    await _msg(db_session, conv.id, MessageRole.user, "first", at=T0 + timedelta(seconds=1))
    await _msg(db_session, conv.id, MessageRole.user, "second", at=T0 + timedelta(seconds=2))
    assert _contents(await repo.list_recent_messages(conv.id, USER_A, 2)) == ["second", "third"]


async def test_other_user_gets_empty_list(db_session):
    repo, conv = await _seed_conversation(db_session, USER_A, 2)
    assert await repo.list_recent_messages(conv.id, USER_B, 10) == []
    # chủ hội thoại vẫn đọc được — xác nhận [] ở trên là do cô lập, không phải do dữ liệu rỗng
    assert len(await repo.list_recent_messages(conv.id, USER_A, 10)) == 4


async def test_does_not_leak_messages_of_other_conversations(db_session):
    repo, conv_a = await _seed_conversation(db_session, USER_A, 2, prefix="a")
    _repo, conv_a2 = await _seed_conversation(db_session, USER_A, 2, prefix="a2")
    _repo, conv_b = await _seed_conversation(db_session, USER_B, 2, prefix="b")

    assert _contents(await repo.list_recent_messages(conv_a.id, USER_A, 10)) == [
        "a-q0",
        "a-a0",
        "a-q1",
        "a-a1",
    ]
    # hội thoại khác của CHÍNH user đó cũng không lẫn vào
    assert all(
        m.conversation_id == conv_a2.id
        for m in await repo.list_recent_messages(conv_a2.id, USER_A, 10)
    )
    assert _contents(await repo.list_recent_messages(conv_b.id, USER_B, 10)) == [
        "b-q0",
        "b-a0",
        "b-q1",
        "b-a1",
    ]
    assert await repo.list_recent_messages(conv_b.id, USER_A, 10) == []


async def test_unknown_conversation_gets_empty_list(db_session):
    repo = ConversationRepository(db_session)
    assert await repo.list_recent_messages("conv-does-not-exist", USER_A, 10) == []


async def test_conversation_without_messages_gets_empty_list(db_session):
    repo = ConversationRepository(db_session)
    conv = await repo.create(user_id=USER_A)
    assert await repo.list_recent_messages(conv.id, USER_A, 10) == []


async def test_non_positive_limit_returns_empty_without_touching_db(db_session, test_engine):
    repo, conv = await _seed_conversation(db_session, USER_A, 2)

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", _record)
    try:
        assert await repo.list_recent_messages(conv.id, USER_A, 0) == []
        assert await repo.list_recent_messages(conv.id, USER_A, -5) == []
        assert statements == []
        # đối chứng: listener có bắt được truy vấn thật
        assert len(await repo.list_recent_messages(conv.id, USER_A, 1)) == 1
        assert len(statements) == 1
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _record)


async def test_same_created_at_user_comes_before_assistant(db_session):
    """Trùng `created_at`: user đứng trước assistant, bất kể `id` và thứ tự INSERT."""
    repo = ConversationRepository(db_session)
    conv = await repo.create(user_id=USER_A)
    # id cố ý ngược với thứ tự mong muốn, và assistant được INSERT trước
    await _msg(
        db_session, conv.id, MessageRole.assistant, "answer", at=T0, id_="tie-0000-assistant"
    )
    await _msg(db_session, conv.id, MessageRole.user, "question", at=T0, id_="tie-9999-user")

    assert _contents(await repo.list_recent_messages(conv.id, USER_A, 10)) == ["question", "answer"]
    # cắt bằng limit giữa hai tin nhắn trùng giờ: giữ tin nhắn đứng SAU (assistant)
    assert _contents(await repo.list_recent_messages(conv.id, USER_A, 1)) == ["answer"]


async def test_same_created_at_and_role_falls_back_to_id(db_session):
    """Trùng cả `created_at` lẫn role: xếp theo `id` tăng dần, lặp lại được."""
    repo = ConversationRepository(db_session)
    conv = await repo.create(user_id=USER_A)
    await _msg(db_session, conv.id, MessageRole.user, "id-c", at=T0, id_="tie-same-role-c")
    await _msg(db_session, conv.id, MessageRole.user, "id-a", at=T0, id_="tie-same-role-a")
    await _msg(db_session, conv.id, MessageRole.user, "id-b", at=T0, id_="tie-same-role-b")

    first = _contents(await repo.list_recent_messages(conv.id, USER_A, 10))
    assert first == ["id-a", "id-b", "id-c"]
    assert _contents(await repo.list_recent_messages(conv.id, USER_A, 10)) == first
    assert _contents(await repo.list_recent_messages(conv.id, USER_A, 2)) == ["id-b", "id-c"]


async def test_tie_is_only_a_secondary_key(db_session):
    """Khoá phụ theo role không được lấn `created_at`: assistant cũ vẫn đứng trước user mới."""
    repo = ConversationRepository(db_session)
    conv = await repo.create(user_id=USER_A)
    await _msg(db_session, conv.id, MessageRole.assistant, "old-answer", at=T0)
    await _msg(db_session, conv.id, MessageRole.user, "new-question", at=T0 + timedelta(seconds=1))
    assert _contents(await repo.list_recent_messages(conv.id, USER_A, 10)) == [
        "old-answer",
        "new-question",
    ]


async def test_system_role_sorts_between_user_and_assistant_on_tie(db_session):
    repo = ConversationRepository(db_session)
    conv = await repo.create(user_id=USER_A)
    await _msg(db_session, conv.id, MessageRole.assistant, "a", at=T0)
    await _msg(db_session, conv.id, MessageRole.system, "s", at=T0)
    await _msg(db_session, conv.id, MessageRole.user, "u", at=T0)
    assert _contents(await repo.list_recent_messages(conv.id, USER_A, 10)) == ["u", "s", "a"]


async def test_content_is_returned_raw_with_citation_marker(db_session):
    """Repo KHÔNG bóc marker `<!--citations:...-->`; việc đó thuộc nơi dựng prompt."""
    repo = ConversationRepository(db_session)
    conv = await repo.create(user_id=USER_A)
    raw = 'Câu trả lời [1].\n<!--citations:[{"chunk_id":"c1"}]-->'
    await _msg(db_session, conv.id, MessageRole.assistant, raw, at=T0)
    messages = await repo.list_recent_messages(conv.id, USER_A, 1)
    assert messages[0].content == raw


async def test_relationships_are_not_loaded(db_session):
    """Không kéo citations/attachments/conversation: chỉ 1 câu SELECT, quan hệ còn unloaded."""
    repo, conv = await _seed_conversation(db_session, USER_A, 2)
    # bỏ identity map để kết quả là object mới nạp từ truy vấn, không phải object lúc seed
    db_session.expunge_all()

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", _record)
    try:
        messages = await repo.list_recent_messages(conv.id, USER_A, 10)
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert len(messages) == 4
    assert len(statements) == 1
    for msg in messages:
        assert {"citations", "attachments", "conversation"} <= instance_state(msg).unloaded
