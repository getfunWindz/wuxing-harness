"""S1-B：运行尝试证据位 + 预算耗尽诚实文案。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.mock import MockLlmProvider
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.runner_support import _test_run_attempted
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


def test_test_run_attempted_predicate():
    assert _test_run_attempted("python -m pytest -q")
    assert _test_run_attempted("python -m unittest discover")
    assert not _test_run_attempted("python --version")
    assert not _test_run_attempted("")


def _mk_runner(**cfg_kw):
    cfg = EngineConfig(**cfg_kw)
    reg = DomainRegistry(cfg)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    return Runner(cfg, reg, ws, MockLlmProvider(), BUILTIN_TOOLS(ws))


def test_note_evidence_records_run_attempted_even_on_failure_output():
    r = _mk_runner()
    r._note_evidence("bash", {"command": "python -m pytest -q"}, "ok",
                     "FAILED tests/test_x.py::test_a - assert 1 == 2")
    assert getattr(r, "_run_attempted", False) is True
    assert getattr(r, "_run_ok", False) is False  # 未通过——通过物证语义不变


def test_exit_failure_budget_with_attempted_failed_run():
    r = _mk_runner()
    r._run_attempted = True
    r._run_ok = False
    r._fail_reason = ""
    cls, msg = r._exit_failure()
    assert cls == "budget"
    assert "已运行测试但未通过" in msg


def test_exit_failure_budget_without_attempted_run():
    r = _mk_runner()
    r._run_attempted = False
    r._fail_reason = ""
    cls, msg = r._exit_failure()
    assert cls == "budget"
    assert "未产出达标产物" in msg


def test_exit_failure_stalled_keeps_class_and_summary():
    r = _mk_runner()
    r._fail_reason = "guard: stalled (no progress)"
    cls, msg = r._exit_failure()
    assert cls == "stalled"
    assert "无进展早停" in msg


def test_classify_failure_prefix_contract():
    """文案前缀是分类器输入契约（不得破坏既有归因）。"""
    from wuxing.repairer import classify_failure
    r = _mk_runner()
    r._run_attempted = True
    _, msg = r._exit_failure()
    assert classify_failure(msg) == "budget"
    r2 = _mk_runner()
    r2._fail_reason = "guard: stalled (no progress)"
    _, msg2 = r2._exit_failure()
    assert classify_failure(msg2) == "budget"  # stalled→budget 口径不变
