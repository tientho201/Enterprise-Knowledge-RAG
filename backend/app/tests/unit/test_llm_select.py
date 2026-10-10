"""Helper chọn LLM theo state (`app/agents/llm_select.py`) — T20.

Kiểm:

- Uỷ thác đúng 3 giá trị `model` / `api_key` / `base_url` cho `get_llm_for_request`.
- Khớp từng nhánh với `agents/generator.py::_get_llm` (cùng tham số gửi xuống factory).
- Ranh giới an toàn (chạy với factory THẬT): không có `api_key` → LLM mặc định của server,
  `base_url`/`model` của người dùng bị bỏ qua — khoá của server không đi tới endpoint lạ.
- Bí mật: khoá không vào log, không vào thông điệp lỗi, không bị cache ở cấp module.
- Lỗi của factory nổi thẳng lên, không rơi về LLM mặc định.

Không gọi mạng: dựng `AsyncOpenAI` không phát request nào. Mọi khoá dưới đây đều là giả.
"""

import ast
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from app.agents import llm_select as llm_select_module
from app.agents.llm_select import get_llm_for_state
from app.agents.state import AgentState
from app.core.config import settings
from app.llm import factory as factory_module
from app.llm.base import BaseLLM
from app.llm.openai_llm import OpenAILLM

FAKE_USER_KEY = "test-key-not-real"
FAKE_SERVER_KEY = "server-key-not-real"
USER_BASE_URL = "https://byom.example.invalid/v1"
USER_MODEL = "user-model-not-real"

BACKEND_DIR = Path(__file__).resolve().parents[3]


def _state(**overrides: Any) -> AgentState:
    """State tối thiểu; chỉ các field BYOM là có nghĩa với helper."""
    return cast(AgentState, {"query": "xin chào", **overrides})


class _Recorder:
    """Thay `get_llm_for_request`: ghi lại tham số, trả về một sentinel."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = cast(BaseLLM, object())

    def __call__(self, **kwargs: Any) -> BaseLLM:
        self.calls.append(kwargs)
        return self.result


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(llm_select_module, "get_llm_for_request", rec)
    return rec


@pytest.fixture
def default_llm(monkeypatch: pytest.MonkeyPatch) -> BaseLLM:
    """Factory THẬT, nhưng `get_llm()` trả sentinel (không đụng lru_cache, không cần khoá
    server) và khoá server là giá trị giả nhận diện được."""
    sentinel = cast(BaseLLM, object())
    monkeypatch.setattr(factory_module, "get_llm", lambda: sentinel)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", FAKE_SERVER_KEY)
    return sentinel


# Các nhánh cần khớp với generator._get_llm. Mỗi phần tử là phần BYOM của state.
BRANCHES: list[dict[str, Any]] = [
    {},  # thiếu hẳn cả 3 key
    {"model": None, "api_key": None, "base_url": None},
    {"model": USER_MODEL, "api_key": "", "base_url": USER_BASE_URL},
    {"model": USER_MODEL, "api_key": "   ", "base_url": USER_BASE_URL},
    {"model": USER_MODEL, "api_key": None, "base_url": USER_BASE_URL},
    {"model": USER_MODEL, "base_url": USER_BASE_URL},
    {"model": USER_MODEL, "api_key": FAKE_USER_KEY, "base_url": USER_BASE_URL},
    {"model": None, "api_key": FAKE_USER_KEY, "base_url": USER_BASE_URL},
    {"model": USER_MODEL, "api_key": FAKE_USER_KEY, "base_url": None},
    {"api_key": FAKE_USER_KEY},
]


# ---------------------------------------------------------------------------
# Uỷ thác cho factory
# ---------------------------------------------------------------------------


def test_passes_all_three_values_to_factory(recorder: _Recorder) -> None:
    result = get_llm_for_state(
        _state(model=USER_MODEL, api_key=FAKE_USER_KEY, base_url=USER_BASE_URL)
    )

    assert result is recorder.result
    assert recorder.calls == [
        {"model": USER_MODEL, "api_key": FAKE_USER_KEY, "base_url": USER_BASE_URL}
    ]


def test_missing_keys_are_passed_as_none(recorder: _Recorder) -> None:
    get_llm_for_state(_state())

    assert recorder.calls == [{"model": None, "api_key": None, "base_url": None}]


def test_values_are_not_normalised(recorder: _Recorder) -> None:
    """Helper không strip/đổi giá trị: quyết định thuộc về factory, như generator._get_llm."""
    get_llm_for_state(_state(model=" m ", api_key="   ", base_url=" http://x "))

    assert recorder.calls == [{"model": " m ", "api_key": "   ", "base_url": " http://x "}]


@pytest.mark.parametrize("byom", BRANCHES)
def test_same_factory_arguments_as_generator_get_llm(
    byom: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents import generator as generator_module

    if not hasattr(generator_module, "_get_llm"):
        pytest.skip("generator._get_llm không còn (đã chuyển sang dùng helper này)")

    helper_rec, generator_rec = _Recorder(), _Recorder()
    monkeypatch.setattr(llm_select_module, "get_llm_for_request", helper_rec)
    monkeypatch.setattr(generator_module, "get_llm_for_request", generator_rec)
    state = _state(**byom)

    get_llm_for_state(state)
    generator_module._get_llm(state)

    assert len(helper_rec.calls) == 1
    if not generator_rec.calls:
        pytest.skip("generator._get_llm không còn gọi get_llm_for_request trực tiếp")
    assert helper_rec.calls == generator_rec.calls


# ---------------------------------------------------------------------------
# Ranh giới an toàn — factory thật
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "byom",
    [
        {},
        {"model": None, "api_key": None, "base_url": None},
        {"model": USER_MODEL, "api_key": None, "base_url": USER_BASE_URL},
        {"model": USER_MODEL, "api_key": "", "base_url": USER_BASE_URL},
        {"model": USER_MODEL, "base_url": USER_BASE_URL},
        {"base_url": USER_BASE_URL},
    ],
)
def test_without_api_key_returns_server_default(
    byom: dict[str, Any], default_llm: BaseLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Không có khoá của người dùng → đúng đối tượng get_llm(); base_url/model bị bỏ qua.

    Nếu nhánh này dựng client mới thì khoá của server sẽ bị gửi tới `base_url` lạ
    (OpenAILLM lấy `settings.OPENAI_API_KEY` khi api_key rỗng) → chặn hẳn việc dựng.
    """

    def _must_not_build(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("không được dựng OpenAILLM khi state không có api_key")

    monkeypatch.setattr("app.llm.openai_llm.OpenAILLM", _must_not_build)

    assert get_llm_for_state(_state(**byom)) is default_llm


def test_with_api_key_builds_user_client(default_llm: BaseLLM) -> None:
    llm = get_llm_for_state(_state(model=USER_MODEL, api_key=FAKE_USER_KEY, base_url=USER_BASE_URL))

    assert llm is not default_llm
    assert isinstance(llm, OpenAILLM)
    assert llm.client.api_key == FAKE_USER_KEY
    assert FAKE_SERVER_KEY not in llm.client.api_key
    assert str(llm.client.base_url).rstrip("/") == USER_BASE_URL
    assert llm.model == USER_MODEL


def test_with_api_key_but_no_model_or_base_url(default_llm: BaseLLM) -> None:
    """Thiếu model → model mặc định của server; thiếu base_url → endpoint mặc định của SDK.
    Vẫn là khoá của NGƯỜI DÙNG, không phải khoá server."""
    llm = get_llm_for_state(_state(api_key=FAKE_USER_KEY))

    assert isinstance(llm, OpenAILLM)
    assert llm.client.api_key == FAKE_USER_KEY
    assert llm.model == settings.OPENAI_MODEL
    assert "byom.example.invalid" not in str(llm.client.base_url)


def test_whitespace_api_key_never_uses_server_key(default_llm: BaseLLM) -> None:
    """Hiện trạng factory (helper khớp theo, không sửa): khoá chỉ gồm khoảng trắng là
    truthy → dựng client BYOM với chính chuỗi đó, KHÔNG rơi về get_llm(). Điều phải giữ:
    khoá của server không đi kèm base_url của người dùng."""
    llm = get_llm_for_state(_state(model=USER_MODEL, api_key="   ", base_url=USER_BASE_URL))

    assert llm is not default_llm
    assert isinstance(llm, OpenAILLM)
    assert llm.client.api_key == "   "
    assert FAKE_SERVER_KEY not in llm.client.api_key


def test_user_client_is_not_cached_between_calls(default_llm: BaseLLM) -> None:
    first = get_llm_for_state(_state(api_key=FAKE_USER_KEY, base_url=USER_BASE_URL))
    second = get_llm_for_state(_state(api_key="other-test-key-not-real", base_url=USER_BASE_URL))
    third = get_llm_for_state(_state())

    assert first is not second
    assert isinstance(second, OpenAILLM)
    assert second.client.api_key == "other-test-key-not-real"
    # Request sau không có khoá không được thừa hưởng client BYOM của request trước.
    assert third is default_llm


# ---------------------------------------------------------------------------
# Lỗi và bí mật
# ---------------------------------------------------------------------------


def test_factory_error_propagates_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Không bắt lỗi rồi rơi về LLM mặc định (sẽ âm thầm gửi dữ liệu BYOM tới server LLM),
    không bọc lại lỗi (không thêm tham số vào thông điệp)."""
    boom = ValueError("cấu hình model tùy chỉnh không hợp lệ")
    fallback_calls: list[int] = []

    def _raise(**kwargs: Any) -> BaseLLM:
        raise boom

    monkeypatch.setattr(llm_select_module, "get_llm_for_request", _raise)
    monkeypatch.setattr(factory_module, "get_llm", lambda: fallback_calls.append(1))

    with pytest.raises(ValueError) as excinfo:
        get_llm_for_state(_state(model=USER_MODEL, api_key=FAKE_USER_KEY, base_url=USER_BASE_URL))

    assert excinfo.value is boom
    assert fallback_calls == []
    assert FAKE_USER_KEY not in str(excinfo.value)
    assert FAKE_USER_KEY not in repr(excinfo.value)


def test_api_key_not_logged(default_llm: BaseLLM, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        get_llm_for_state(_state(model=USER_MODEL, api_key=FAKE_USER_KEY, base_url=USER_BASE_URL))
        get_llm_for_state(_state())

    assert FAKE_USER_KEY not in caplog.text
    assert FAKE_SERVER_KEY not in caplog.text
    assert all(FAKE_USER_KEY not in str(record.args) for record in caplog.records)


def test_api_key_not_logged_when_factory_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _raise(**kwargs: Any) -> BaseLLM:
        raise RuntimeError("factory hỏng")

    monkeypatch.setattr(llm_select_module, "get_llm_for_request", _raise)

    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError) as excinfo:
        get_llm_for_state(_state(api_key=FAKE_USER_KEY, base_url=USER_BASE_URL))

    assert FAKE_USER_KEY not in caplog.text
    assert FAKE_USER_KEY not in str(excinfo.value)


def test_no_module_level_state_holds_the_key(default_llm: BaseLLM) -> None:
    before = set(vars(llm_select_module))
    get_llm_for_state(_state(model=USER_MODEL, api_key=FAKE_USER_KEY, base_url=USER_BASE_URL))

    assert set(vars(llm_select_module)) == before
    assert not hasattr(get_llm_for_state, "cache_info")
    assert all(FAKE_USER_KEY not in repr(value) for value in vars(llm_select_module).values())


# ---------------------------------------------------------------------------
# Cấu trúc module
# ---------------------------------------------------------------------------


def test_module_only_goes_through_factory() -> None:
    """Không tạo client OpenAI trực tiếp, không logging, không cache."""
    source = Path(llm_select_module.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")

    assert imported == {
        "__future__",
        "typing",
        "app.llm.base",
        "app.llm.factory",
        "app.agents.state",
    }


def test_imports_cleanly_in_fresh_interpreter() -> None:
    """Không import vòng, không kéo openai/qdrant/state lúc import (AgentState chỉ dùng
    khi type-check)."""
    code = (
        "import sys; import app.agents.llm_select as m; "
        "assert callable(m.get_llm_for_state); "
        "assert 'app.agents.state' not in sys.modules; "
        "assert 'app.rag.retriever' not in sys.modules; "
        "assert 'openai' not in sys.modules"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr
