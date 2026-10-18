"""TDD：FSC 编排接线——匹配发动（同目录碎片跨轮延续）+ trace 观测。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.orchestrator import Orchestrator
from wuxing.protocols import UnitResult
from wuxing.registry import DomainRegistry
from wuxing.session_pool import SessionPool
from wuxing.trace import TraceLogger
from wuxing.workspace import Workspace


class _FakeRunner:
    emit_event = None

    def __init__(self, sink):
        self.sink = sink
        self._messages = [{"role": "system", "content": "S"}]

    def run_unit(self, unit_id, domain_id, params, resume_session=None,
                 bypass_confirm=False, continue_from=None, cancel=None,
                 llm_candidate=0):
        self.sink.append((unit_id, list(continue_from or [])))
        if continue_from:
            self._messages = list(continue_from) + [
                {"role": "user", "content": params["goal"]}]
        else:
            self._messages = [{"role": "system", "content": "S"},
                              {"role": "user", "content": params["goal"]}]
        return UnitResult(unit_id=unit_id, domain_id=domain_id, status="ok")


def test_fsc_match_fires_across_rounds_and_records_trace():
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    cfg = EngineConfig()
    pool = SessionPool(retention_rounds=4)
    seen = []
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, None, [],
                        session_pool=pool,
                        trace=TraceLogger(ws.root / "trace.jsonl"))
    orch._make_runner = lambda: _FakeRunner(seen)
    frags1 = [{"fragment_id": "F-1", "domain": "execute", "deps": [],
               "text": "更新 docs/a.md 内容", "deliverables": []}]
    orch.run(frags1, "t1")
    frags2 = [{"fragment_id": "F-2", "domain": "execute", "deps": [],
               "text": "继续完善 docs/b.md", "deliverables": []}]
    orch.run(frags2, "t2")
    assert seen[0][1] == [], "首轮无延续"
    assert seen[1][1], "次轮必须延续（docs 目录键命中）"
    rows = orch.trace.load()
    assert any(r["event"] == "session_reused" for r in rows), rows
    assert any(r.get("key") == "docs" for r in rows if r["event"] == "session_reused")


def test_fsc_disabled_no_session_pool_no_change():
    """未启用 FSC：行为与现状一致（无锁/无延续/无 trace 事件）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    cfg = EngineConfig()
    seen = []
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, None, [])
    orch._make_runner = lambda: _FakeRunner(seen)
    orch.run([{"fragment_id": "F-1", "domain": "execute", "deps": [],
               "text": "更新 docs/a.md", "deliverables": []}], "t1")
    orch.run([{"fragment_id": "F-2", "domain": "execute", "deps": [],
               "text": "继续 docs/b.md", "deliverables": []}], "t2")
    assert seen[0][1] == [] and seen[1][1] == [], "未启用不得延续"


def test_drained_switch_event_logs_own_key():
    """六轮审查 B3：池事件被其它键的单元 drain 时，trace 必须用事件自身键
    （原实现用当前单位的键标注——键归属错配，评测原料失真）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    cfg = EngineConfig()
    pool = SessionPool()
    pool._events.append({"event": "session_switched",
                         "key": ("execute", frozenset({"other"})),
                         "ratio": 0.9})
    seen = []
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, None, [],
                        session_pool=pool,
                        trace=TraceLogger(ws.root / "t.jsonl"))
    orch._make_runner = lambda: _FakeRunner(seen)
    orch._run_one({"fragment_id": "F-1", "domain": "execute", "deps": [],
                   "text": "更新 docs/a.md"}, "t", lambda e: None, {})
    rows = orch.trace.load()
    sw = [r for r in rows if r.get("event") == "session_switched"]
    assert sw and sw[0].get("key") == "other", \
        f"键归属必须用事件自身键（实际 {[r.get('key') for r in sw]}）"


def test_plan_label_injection_keys_execute_fragments():
    """C 全形态（A 阶段）：plan 输出的『工作流：xxx』标签注入 execute 碎片——
    无路径文本的碎片获得工作流键，且跨轮同工作流可复用。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    cfg = EngineConfig()
    pool = SessionPool(retention_rounds=4)
    seen = []

    class PlanRunner(_FakeRunner):
        def run_unit(self, unit_id, domain_id, params, resume_session=None,
                     bypass_confirm=False, continue_from=None, cancel=None,
                     llm_candidate=0):
            self.sink.append((unit_id, list(continue_from or [])))
            self._messages = [{"role": "system", "content": "S"},
                              {"role": "user",
                               "content": "## 实施工作流\n"
                                          "- 工作流：docs——更新手册文档\n"}]
            return UnitResult(unit_id=unit_id, domain_id=domain_id, status="ok",
                              logs=["## 实施工作流\n- 工作流：docs——更新手册文档"])

    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, None, [],
                        session_pool=pool,
                        trace=TraceLogger(ws.root / "trace.jsonl"))
    orch._make_runner = lambda: PlanRunner(seen)
    orch.run([{"fragment_id": "F-1", "domain": "plan", "deps": [],
               "text": "总任务"},
              {"fragment_id": "F-2", "domain": "execute", "deps": ["F-1"],
               "text": "更新用户手册文档"}], "t1")
    rows = orch.trace.load()
    assert any(r.get("event") == "session_created" and r.get("key") == "docs"
               for r in rows), rows
    # 次轮：plan 再输出同标签 → execute 碎片复用 docs 会话（跨轮）
    orch.run([{"fragment_id": "F-3", "domain": "plan", "deps": [],
               "text": "继续任务"},
              {"fragment_id": "F-4", "domain": "execute", "deps": ["F-3"],
               "text": "更新用户手册文档"}], "t2")
    rows2 = orch.trace.load()
    assert any(r.get("event") == "session_reused" and r.get("key") == "docs"
               for r in rows2), rows2


def test_key_lock_released_when_match_raises(monkeypatch):
    """六轮审查 B2：延续段（match/审计/trace）异常必须释放同键锁。

    原实现：锁在 try 外获取、释放仅在 finally 内——match 抛错即永久占锁，
    该键后续单元在批次中永久阻塞（占满 worker 可拖停整个任务）。"""
    import pytest

    from wuxing.session_pool import fsc_key

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    cfg = EngineConfig()
    pool = SessionPool()
    seen = []
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, None, [],
                        session_pool=pool)
    orch._make_runner = lambda: _FakeRunner(seen)

    def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(pool, "match", _boom)
    frag = {"fragment_id": "F-1", "domain": "execute", "deps": [],
            "text": "更新 docs/a.md"}
    with pytest.raises(RuntimeError):
        orch._run_one(frag, "t", lambda e: None, {})
    key = fsc_key("execute", "更新 docs/a.md", "")
    lock = pool.key_lock(key)
    assert lock.acquire(timeout=0.2), "异常后同键锁必须已释放"
    lock.release()
