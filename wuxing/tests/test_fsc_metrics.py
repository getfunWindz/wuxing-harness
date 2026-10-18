"""TDD：FSC 健康指标与阈值事件（壳 UI 阶段 4 · 引擎对齐项⑩）。

- metrics["fsc"]：任务级差值（复用/审计/切换/覆盖）+ 池内会话数
- 60% 审计 → FscAudit 事件；80% 切换 → FscSwitch 事件（壳流内可见）
"""
import pathlib
import tempfile


def test_pool_snapshot_and_metrics_delta(tmp_path):
    from wuxing.engine import Engine
    eng = Engine(workdir=tmp_path, auto_confirm=True)

    class FakePool:
        def stats(self):
            return {"matched": 5, "reused": 3, "audited": 2, "switched": 1,
                    "evicted": 1, "keyed": 7, "unkeyed": 3, "pool_size": 4,
                    "over_window": 0}

    eng.session_pool = FakePool()
    eng._pool_baseline = {"matched": 4, "reused": 2, "audited": 1,
                          "switched": 0, "evicted": 0, "keyed": 6, "unkeyed": 2,
                          "pool_size": 3, "over_window": 0}
    m = eng._collect_metrics([], eng._cache_snapshot())
    fsc = m["fsc"]
    assert fsc["reused"] == 1
    assert fsc["sessions"] == 4
    assert fsc["coverage"] == 0.5          # keyed_d=1 / (1+1)
    assert fsc["audited"] == 1 and fsc["switched"] == 1


def test_engine_task_metrics_include_fsc(tmp_path):
    from wuxing.engine import Engine
    eng = Engine(workdir=tmp_path, auto_confirm=True)
    res = eng.run_task("写一篇请假邮件")
    assert "fsc" in res.metrics, res.metrics
    fsc = res.metrics["fsc"]
    assert isinstance(fsc["reused"], int)
    assert "coverage" in fsc
    assert "cost" in res.metrics, res.metrics
    assert "estimate" in res.metrics["cost"]


def _orch_with_pool(pool, seen_events):
    from wuxing.config import EngineConfig
    from wuxing.orchestrator import Orchestrator
    from wuxing.protocols import UnitResult
    from wuxing.registry import DomainRegistry
    from wuxing.workspace import Workspace

    class FakeRunner:
        emit_event = None
        def __init__(self):
            self._messages = [{"role": "system", "content": "S"}]
        def run_unit(self, unit_id, domain_id, params, resume_session=None,
                     bypass_confirm=False, continue_from=None, cancel=None,
                     llm_candidate=0):
            self._messages = list(continue_from or []) + [
                {"role": "user", "content": "x" * 300}]
            return UnitResult(unit_id=unit_id, domain_id=domain_id, status="ok")

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    cfg = EngineConfig()
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, None, [],
                        session_pool=pool,
                        trace=None)
    orch._make_runner = FakeRunner

    def on_event(e):
        seen_events.append(e)

    return orch, on_event


def _frag(i):
    return [{"fragment_id": f"F-{i}", "domain": "execute", "deps": [],
             "text": "更新 docs/a.md", "deliverables": []}]


def test_fsc_audit_event_emitted():
    """60% 审计注入 → FscAudit 事件（含阈值比例）。"""
    from wuxing.session_pool import SessionPool
    pool = SessionPool(context_window=1000, audit_ratio=0.6, switch_ratio=0.8)
    events = []
    orch, on_event = _orch_with_pool(pool, events)
    pool.retain(("execute", frozenset({"docs"})), "execute",
                [{"role": "user", "content": "x" * 650}],
                unit_id="U-1", current_round=1)
    orch.run(_frag(2), "t2", on_event=on_event)
    audits = [e for e in events if type(e).__name__ == "FscAudit"]
    assert audits, [type(e).__name__ for e in events]
    assert audits[0].ratio >= 0.6


def test_fsc_switch_event_emitted():
    """80% 切换 → FscSwitch 事件（即使 auto_confirm 也可见）。"""
    from wuxing.session_pool import SessionPool
    pool = SessionPool(context_window=1000, audit_ratio=0.6, switch_ratio=0.8)
    events = []
    orch, on_event = _orch_with_pool(pool, events)
    key = ("execute", frozenset({"docs"}))
    pool.retain(key, "execute", [{"role": "user", "content": "x" * 850}],
                unit_id="U-1", current_round=1)
    pool.mark_audited(key)
    orch.run(_frag(2), "t2", on_event=on_event)
    switches = [e for e in events if type(e).__name__ == "FscSwitch"]
    assert switches, [type(e).__name__ for e in events]
    assert switches[0].ratio >= 0.8
