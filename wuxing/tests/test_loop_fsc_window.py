"""TDD：上下文窗口机制——窗口解析链 / 会话占用率 / 60% 审计 / 80% 切换。"""
import pathlib
import tempfile


def test_window_resolution_chain():
    """解析链：配置/官方表命中 → 默认兜底（API 不返回窗口——实测）。"""
    from wuxing.context_window import resolve_context_window
    assert resolve_context_window("deepseek:deepseek-flash") == 1_000_000
    assert resolve_context_window("openai:gpt-x") == 200_000


def test_session_ratio_audit_then_switch():
    """60%：审计标记（一次，标记后清除）；80%：切换（不再匹配 + switched 统计）。"""
    from wuxing.session_pool import SessionPool
    pool = SessionPool(context_window=1000, audit_ratio=0.6, switch_ratio=0.8)
    key = ("execute", frozenset({"docs"}))
    pool.retain(key, "execute", [{"role": "user", "content": "x" * 650}],
                unit_id="U-1", current_round=1)
    s = pool.match("execute", key, 2)
    assert s is not None and s.audit_pending is True, "65% 必须标记审计"
    pool.mark_audited(key)
    s2 = pool.match("execute", key, 3)
    assert s2 is not None and s2.audit_pending is False, "审计一次后不再重复"
    # 增长到 85% → 切换
    pool.retain(key, "execute", [{"role": "user", "content": "x" * 850}],
                unit_id="U-2", current_round=3, reused=True)
    assert pool.match("execute", key, 4) is None, "85% 必须切换（不再延续）"
    assert pool.stats()["switched"] == 1, pool.stats()


def test_orchestrator_appends_audit_instruction_and_traces():
    """编排：审计待办 → 延续消息尾部 append 审计指令 + trace session_audit（一次）。"""
    from wuxing.config import EngineConfig
    from wuxing.orchestrator import Orchestrator
    from wuxing.protocols import UnitResult
    from wuxing.registry import DomainRegistry
    from wuxing.session_pool import SessionPool
    from wuxing.trace import TraceLogger
    from wuxing.workspace import Workspace

    class FakeRunner:
        emit_event = None
        def __init__(self, sink):
            self.sink = sink
            self._messages = [{"role": "system", "content": "S"}]
        def run_unit(self, unit_id, domain_id, params, resume_session=None,
                     bypass_confirm=False, continue_from=None, cancel=None,
                     llm_candidate=0):
            self.sink.append(list(continue_from or []))
            self._messages = list(continue_from or []) + [
                {"role": "user", "content": "x" * 300}]
            return UnitResult(unit_id=unit_id, domain_id=domain_id, status="ok")

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    cfg = EngineConfig()
    pool = SessionPool(context_window=1000, audit_ratio=0.6, switch_ratio=0.8)
    seen = []
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, None, [],
                        session_pool=pool, trace=TraceLogger(ws.root / "t.jsonl"))
    orch._make_runner = lambda: FakeRunner(seen)
    f = lambda i: [{"fragment_id": f"F-{i}", "domain": "execute", "deps": [],
                    "text": "更新 docs/a.md", "deliverables": []}]
    orch.run(f(1), "t1")   # 建会话（~300 chars）
    orch.run(f(2), "t2")   # 延续（~600+）
    orch.run(f(3), "t3")   # 延续（~900+ → 审计触发在下一次 match）
    audit_seen = [m for msgs in seen for m in msgs
                  if "会话审计" in str(m.get("content", ""))]
    assert audit_seen, "延续消息必须含审计指令"
    rows = orch.trace.load()
    assert sum(1 for r in rows if r["event"] == "session_audit") == 1, rows


def test_audit_fires_once_across_retain_cycles():
    """六轮审查 B1（端到端）：4 轮延续下审计只注入一次。

    原实现 retain 每轮换代丢 audited → 第 3/4 轮连续注入两次审计指令。"""
    from wuxing.config import EngineConfig
    from wuxing.orchestrator import Orchestrator
    from wuxing.protocols import UnitResult
    from wuxing.registry import DomainRegistry
    from wuxing.session_pool import SessionPool
    from wuxing.trace import TraceLogger
    from wuxing.workspace import Workspace

    class FakeRunner:
        emit_event = None

        def __init__(self):
            self._messages = []

        def run_unit(self, unit_id, domain_id, params, resume_session=None,
                     bypass_confirm=False, continue_from=None, cancel=None,
                     llm_candidate=0):
            self._messages = list(continue_from or []) + [
                {"role": "user", "content": "x" * 3000}]
            return UnitResult(unit_id=unit_id, domain_id=domain_id, status="ok")

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    cfg = EngineConfig()
    pool = SessionPool(context_window=10000, audit_ratio=0.6, switch_ratio=0.95)
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, None, [],
                        session_pool=pool,
                        trace=TraceLogger(ws.root / "t.jsonl"))
    orch._make_runner = lambda: FakeRunner()
    for i in range(1, 5):
        orch.run([{"fragment_id": f"F-{i}", "domain": "execute", "deps": [],
                   "text": "更新 docs/a.md", "deliverables": []}], f"t{i}")
    rows = orch.trace.load()
    audits = [r for r in rows if r.get("event") == "session_audit"]
    assert len(audits) == 1, f"审计必须严格一次（实际 {len(audits)}）"


def test_switch_asks_user_in_manual_confirm_mode():
    """六轮审查 B4：80% 切换在 auto_confirm=False 时必须挂起询问用户
    （设计 §4）；auto_confirm=True（headless/真实测试）自动切换。"""
    from wuxing.config import EngineConfig
    from wuxing.orchestrator import Orchestrator
    from wuxing.protocols import UnitResult
    from wuxing.registry import DomainRegistry
    from wuxing.session_pool import SessionPool
    from wuxing.workspace import Workspace

    class FakeRunner:
        emit_event = None

        def __init__(self, sink):
            self.sink = sink
            self._messages = []

        def run_unit(self, unit_id, domain_id, params, resume_session=None,
                     bypass_confirm=False, continue_from=None, cancel=None,
                     llm_candidate=0):
            self.sink.append(unit_id)
            self._messages = list(continue_from or []) + [
                {"role": "user", "content": "n"}]
            return UnitResult(unit_id=unit_id, domain_id=domain_id, status="ok")

    def _mk(auto_confirm):
        ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
        cfg = EngineConfig()
        pool = SessionPool(context_window=1000, audit_ratio=0.6,
                           switch_ratio=0.8)
        key = ("execute", frozenset({"docs"}))
        pool.retain(key, "execute", [{"role": "user", "content": "x" * 850}],
                    unit_id="U-1", current_round=1)
        seen = []
        orch = Orchestrator(cfg, DomainRegistry(cfg), ws, None, [],
                            auto_confirm=auto_confirm, session_pool=pool)
        orch._make_runner = lambda: FakeRunner(seen)
        results = orch.run([{"fragment_id": "F-1", "domain": "execute",
                             "deps": [], "text": "更新 docs/a.md",
                             "deliverables": []}], "t")
        return results, seen, pool

    results, seen, _pool = _mk(auto_confirm=False)
    assert results[0].status == "needs_confirm", results[0].status
    assert seen == [], "询问模式下不得执行（批准后才续跑）"
    results2, seen2, _ = _mk(auto_confirm=True)
    assert results2[0].status == "ok" and seen2 == ["F-1"], \
        "headless 模式自动切换并新开会话执行"
