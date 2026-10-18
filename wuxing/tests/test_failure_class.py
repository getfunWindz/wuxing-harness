"""S1：失败分类字段（provider/budget/stalled）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.mock import MockLlmProvider
from wuxing.protocols import UnitResult
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


def test_unit_result_default_failure_class_empty():
    r = UnitResult(unit_id="U-1", domain_id="plan", status="ok")
    assert r.failure_class == ""


def _mk_runner(llm=None, **cfg_kw):
    cfg = EngineConfig(**cfg_kw)
    reg = DomainRegistry(cfg)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    return Runner(cfg, reg, ws, llm or MockLlmProvider(), BUILTIN_TOOLS(ws))


class _Boom:
    """provider 假体：chat 直接抛错（模拟 ReadTimeout）。"""
    def name(self):
        return "boom"

    def spec(self):
        return "mock"

    def chat(self, messages, tools=None):
        raise RuntimeError("provider: ReadTimeout: sim")


def test_provider_failure_marks_provider_class():
    r = _mk_runner(llm=_Boom())
    res = r.run_unit("U-1", "plan", {"goal": "plan:任意任务"})
    assert res.status == "failed"
    assert res.failure_class == "provider"


def test_provider_failure_trace_field_unchanged():
    """兼容纪律：trace unit_done.provider_error 不回归（evaluate.py 消费）。"""
    class _Trace:
        def __init__(self):
            self.rows = []

        def log(self, event, *a, **k):
            self.rows.append({"event": event, **k})

    r = _mk_runner(llm=_Boom())
    r.trace = _Trace()
    res = r.run_unit("U-1", "plan", {"goal": "plan:任意任务"})
    row = [x for x in r.trace.rows
           if x["event"] == "unit_done" and x.get("status") == "failed"][-1]
    assert row.get("provider_error") is True
    assert res.failure_class == "provider"
