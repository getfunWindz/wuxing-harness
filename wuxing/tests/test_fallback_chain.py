"""S1-A/L2：候选感知路由 + 降级链消费。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.mock import MockLlmProvider
from wuxing.llm.router import ModelRouter
from wuxing.orchestrator import Orchestrator
from wuxing.registry import DomainRegistry
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


class OkMock(MockLlmProvider):
    def name(self):
        return "ok"


class BoomMock(MockLlmProvider):
    def name(self):
        return "boom"

    def chat(self, messages, tools=None):
        raise RuntimeError("provider: ReadTimeout: sim")


class _Trace:
    def __init__(self):
        self.rows = []

    def log(self, event, *a, **k):
        self.rows.append({"event": event, **k})


def test_router_candidate_count_and_index():
    r = ModelRouter({"plan": ["mock", "mock"]}, providers=None)
    assert r.candidate_count("plan") == 2
    p0 = r.for_domain("plan", candidate_index=0)
    p1 = r.for_domain("plan", candidate_index=1)
    assert p0 is not None and p1 is not None
    assert r.candidate_count("execute") == 1  # 未配置域回退单候选


def test_orchestrator_falls_back_to_next_candidate():
    cfg = EngineConfig(provider_retry_max=0)
    reg = DomainRegistry(cfg)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    provs = {0: BoomMock(), 1: OkMock()}
    trace = _Trace()

    def llm_for(domain, key=None, candidate=0):
        return provs[candidate]

    o = Orchestrator(cfg, reg, ws, provs[0], BUILTIN_TOOLS(ws),
                     llm_for=llm_for, llm_candidate_count=lambda d: 2,
                     trace=trace)
    frags = [{"fragment_id": "F-1", "domain": "plan", "deps": []}]
    results = o.run(frags, task_text="x")
    assert results[0].status == "ok"
    assert any(r["event"] == "provider_fallback" for r in trace.rows)


def test_unconfigured_fallback_is_zero_behavior():
    """未配置候选列表（count=1）→ 无降级、无 provider_fallback。"""
    cfg = EngineConfig(provider_retry_max=0)
    reg = DomainRegistry(cfg)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    trace = _Trace()
    o = Orchestrator(cfg, reg, ws, BoomMock(), BUILTIN_TOOLS(ws),
                     llm_candidate_count=lambda d: 1, trace=trace)
    frags = [{"fragment_id": "F-1", "domain": "plan", "deps": []}]
    results = o.run(frags, task_text="x")
    assert results[0].status == "failed"
    assert not any(r["event"] == "provider_fallback" for r in trace.rows)
