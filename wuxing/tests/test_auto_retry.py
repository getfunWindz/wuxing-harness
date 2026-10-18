"""S1-A/L1：provider 抖动有界自动重试（不占手动重跑次数）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.mock import MockLlmProvider
from wuxing.orchestrator import Orchestrator
from wuxing.registry import DomainRegistry
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


class FlakyMock(MockLlmProvider):
    """首调抛 provider 错误，其后正常（同 provider 恢复场景）。"""
    def __init__(self):
        super().__init__()
        self.calls = 0

    def name(self):
        return "flaky"

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("provider: ReadTimeout: sim")
        return super().chat(messages, tools)


class _Trace:
    def __init__(self):
        self.rows = []

    def log(self, event, *a, **k):
        self.rows.append({"event": event, **k})


def _mk_orch(llm, trace=None, **cfg_kw):
    cfg = EngineConfig(provider_retry_backoff_s=0.0, **cfg_kw)
    reg = DomainRegistry(cfg)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    return Orchestrator(cfg, reg, ws, llm, BUILTIN_TOOLS(ws), trace=trace)


def test_provider_failure_retries_once_then_succeeds():
    llm, trace = FlakyMock(), _Trace()
    o = _mk_orch(llm, trace)  # 默认 provider_retry_max=1
    frags = [{"fragment_id": "F-1", "domain": "plan", "deps": []}]
    results = o.run(frags, task_text="x")
    assert results[0].status == "ok"
    assert llm.calls == 2
    assert frags[0]["attempts"] == 1  # 手动重跑机会未被占用
    assert any(r["event"] == "provider_retry" for r in trace.rows)


def test_retry_disabled_by_config():
    llm, trace = FlakyMock(), _Trace()
    o = _mk_orch(llm, trace, provider_retry_max=0)
    frags = [{"fragment_id": "F-1", "domain": "plan", "deps": []}]
    results = o.run(frags, task_text="x")
    assert results[0].status == "failed"
    assert llm.calls == 1
    assert not any(r["event"] == "provider_retry" for r in trace.rows)


def test_retry_exhausted_returns_failed_provider_class():
    class AlwaysBoom(MockLlmProvider):
        def name(self):
            return "boom"

        def chat(self, messages, tools=None):
            raise RuntimeError("provider: ReadTimeout: sim")

    o = _mk_orch(AlwaysBoom())
    frags = [{"fragment_id": "F-1", "domain": "plan", "deps": []}]
    results = o.run(frags, task_text="x")
    assert results[0].status == "failed"
    assert results[0].failure_class == "provider"
