import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.mock import MockLlmProvider
from wuxing.orchestrator import Orchestrator
from wuxing.registry import DomainRegistry
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


def _mk_orch():
    cfg = EngineConfig()
    reg = DomainRegistry(cfg)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    return Orchestrator(cfg, reg, ws, MockLlmProvider(), BUILTIN_TOOLS(ws))

def test_topological_order_respected():
    o = _mk_orch()
    # frags: A(plan) --dep--> B(execute) --dep--> C(verify)
    frags = [
        {"fragment_id": "F-1", "domain": "plan", "deps": []},
        {"fragment_id": "F-2", "domain": "execute", "deps": ["F-1"]},
        {"fragment_id": "F-3", "domain": "verify", "deps": ["F-2"]},
    ]
    results = o.run(frags, task_text="写一篇请假邮件")
    order = [r.unit_id for r in results]
    assert order.index("F-1") < order.index("F-2") < order.index("F-3")

def test_parallel_independent_fragments():
    o = _mk_orch()
    frags = [
        {"fragment_id": "F-1", "domain": "plan", "deps": []},
        {"fragment_id": "F-2", "domain": "execute", "deps": []},
    ]
    results = o.run(frags, task_text="x")
    assert len(results) == 2

def test_failed_unit_does_not_block_others():
    o = _mk_orch()
    frags = [
        {"fragment_id": "F-1", "domain": "plan", "deps": []},
        {"fragment_id": "F-2", "domain": "execute", "deps": []},
    ]
    results = o.run(frags, task_text="plan:永不收敛")
    # 依赖 F-2 无 F-1 产物也可跑（P1 简化），故两者均执行
    assert len(results) == 2


def test_parallel_independent_fragments_concurrent():
    """P16 多手并行：无依赖碎片并发执行（原始构想——多手同时干活）。
    Barrier 确定性并发证明（不依赖 sleep 时序——全量负载下仍可靠）。
    """
    import threading

    from wuxing.config import EngineConfig
    from wuxing.orchestrator import Orchestrator
    from wuxing.registry import DomainRegistry
    from wuxing.tools.builtin import BUILTIN_TOOLS
    from wuxing.workspace import Workspace

    barrier = threading.Barrier(2, timeout=10)  # 两 worker 必须同时进入 chat
    reached = {"n": 0, "lock": threading.Lock()}

    class SlowLlm:
        def name(self): return "slow"
        def spec(self): return "mock"
        def chat(self, messages, tools=None):
            barrier.wait()  # 确定性：并发则双双到达（不用 sleep 窗口）
            with reached["lock"]:
                reached["n"] += 1
            return "方案：计划\n验收标准：完整"

    cfg = EngineConfig(max_parallel_units=2)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = DomainRegistry(cfg)
    orch = Orchestrator(cfg, reg, ws, SlowLlm(), BUILTIN_TOOLS(ws))
    frags = [
        {"fragment_id": "F-1", "domain": "plan", "deps": [], "text": "任务A"},
        {"fragment_id": "F-2", "domain": "plan", "deps": [], "text": "任务B"},
    ]
    res = orch.run(frags, "任务", seed_done=set())
    assert len(res) == 2
    assert all(u.status == "ok" for u in res)
    assert reached["n"] == 2  # Barrier 证明并发（串行则 barrier 超时抛 BrokenBarrier）


def test_parallel_respects_dependencies():
    """依赖链仍串行：F-2 deps=F-1 时顺序正确（后置校验 F-1 产物）。"""
    from wuxing.config import EngineConfig
    from wuxing.orchestrator import Orchestrator
    from wuxing.registry import DomainRegistry
    from wuxing.workspace import Workspace

    order = []

    class OrderLlm:
        def name(self): return "order"
        def spec(self): return "mock"
        def chat(self, messages, tools=None):
            content = messages[-1]["content"] or ""
            # 依赖参数：F-2 的 prompt 应含 F-1 产物（plan 参数=done[F-1]）
            idx = content.rfind("目标")
            order.append(content[idx + 2:][:16] if idx >= 0 else content[:16])
            return "方案：计划\n验收标准：完整"

    cfg = EngineConfig(max_parallel_units=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, OrderLlm(), BUILTIN_TOOLS(ws))
    frags = [
        {"fragment_id": "F-1", "domain": "plan", "deps": [], "text": "任务A"},
        {"fragment_id": "F-2", "domain": "plan", "deps": ["F-1"], "text": "任务B"},
    ]
    res = orch.run(frags, "任务")
    assert all(u.status == "ok" for u in res)
    assert res[1].unit_id == "F-2"  # 顺序稳定（sort by input order）


def test_parallel_batch_done_snapshot_no_race():
    """A 级修复：并行批次提交前对 done 快照——worker 迭代 done 期间主线程
    插入完成单元，不得触发 RuntimeError（dictionary changed size during
    iteration）。

    构造：seed 一个 plan 单元（deliverables 经自定义 file_cache 读取——
    第一次读阻塞），两个无依赖碎片并行；被阻塞的 worker 在 _dep_context
    迭代 done 中，另一 worker 完成后调度器向 done 插入 → 修复前迭代中
    字典变更 → RuntimeError。
    """
    import threading
    import time as _time

    from wuxing.protocols import UnitResult

    class BlockingCache:
        """第一次 get 阻塞（模拟 worker 迭代中的慢读）；其余立即返回。"""
        def __init__(self):
            self._fired = False
            self._lock = threading.Lock()
            self.entered = threading.Event()
            self.release = threading.Event()

        def get(self, path):
            with self._lock:
                fire = not self._fired
                if fire:
                    self._fired = True
            if fire:
                self.entered.set()
                self.release.wait(5)
            return "计划内容"

        def put(self, path, content):
            pass

    class FakeRunner:
        emit_event = None

        def run_unit(self, unit_id, domain_id, params, resume_session=None,
                     **kw):
            return UnitResult(unit_id=unit_id, domain_id=domain_id, status="ok")

    cache = BlockingCache()
    o = _mk_orch()
    o.file_cache = cache
    o._make_runner = lambda: FakeRunner()

    done = {"F-plan": UnitResult(unit_id="F-plan", domain_id="plan",
                                  status="ok", deliverables=["plan.md"])}
    frags = [
        {"fragment_id": "F-a", "domain": "execute", "deps": [], "text": "任务A"},
        {"fragment_id": "F-b", "domain": "execute", "deps": [], "text": "任务B"},
    ]
    results = []

    def _releaser():
        # 等调度器把完成的 worker 插入 done（len==2）后放行阻塞中的 worker
        for _ in range(1000):
            if len(done) >= 2:
                break
            _time.sleep(0.002)
        cache.release.set()

    t = threading.Thread(target=_releaser, daemon=True)
    t.start()
    try:
        o._schedule(frags, "任务", lambda e: None, done, results, None)
    finally:
        cache.release.set()
        t.join(timeout=5)
    assert cache.entered.is_set(), "构造条件必须成立：有 worker 在迭代中被阻塞"
    assert len(results) == 2, f"两个碎片都应有结果：{results}"


def test_plan_cross_domain_dep_deferred_not_cycle():
    """阶段调度修复（2026-09-11 真实测试暴露）：plan 碎片依赖其他域时，
    plan 阶段无就绪 → 以前被误判 cycle 判死并连累下游；修复：延后到
    第二阶段（其他域）调度，不得误判。"""
    o = _mk_orch()
    frags = [
        {"fragment_id": "F-1", "domain": "execute", "deps": []},
        {"fragment_id": "F-2", "domain": "plan", "deps": ["F-1"]},
        {"fragment_id": "F-3", "domain": "execute", "deps": ["F-2"]},
    ]
    results = o.run(frags, task_text="跨阶段依赖任务")
    assert all(r.status == "ok" for r in results), \
        [(r.unit_id, r.status, r.error) for r in results]
    order = [r.unit_id for r in results]
    assert order.index("F-1") < order.index("F-2") < order.index("F-3")


def test_dep_context_verify_gets_larger_injection():
    """G（报告 #6）：verify 注入上限 8000——验收对象完整性
    （planner「正文被截断」类拒绝的根因是 800 字符注入）；其余域维持 800。"""
    from wuxing.protocols import UnitResult
    o = _mk_orch()
    (o.ws.root / "artifact.md").write_text("验收正文" * 2000, encoding="utf-8")
    done = {"F-1": UnitResult(unit_id="F-1", domain_id="execute", status="ok",
                              deliverables=["artifact.md"])}
    _p, result_text, paths = o._dep_context(
        done, {"fragment_id": "V-1", "domain": "verify", "deps": ["F-1"]})
    assert len(result_text) > 5000, f"verify 注入必须完整（实际 {len(result_text)}）"
    assert "artifact.md" in paths
    _p2, exec_text, _p3 = o._dep_context(
        done, {"fragment_id": "E-1", "domain": "execute", "deps": ["F-1"]})
    assert len(exec_text) <= 900, f"非 verify 域维持 800（实际 {len(exec_text)}）"


def test_rewritten_artifact_invalidates_cache_for_later_units():
    """真测修复（REAL-4）：单元重写产物后，后续单元依赖注入必须拿到新内容。

    真测现场（ws-pure）：F-1 写早期 report.md → 缓存被读入 → F-4 重写最终版
    → verify（F-5）注入命中**陈旧缓存**（旧版）→ 与磁盘不一致 → verdict_fail
    → 任务误判失败。FileCache 自身「脏读（快照）」语义保持不变，修复在写入
    边界失效对应条条目。
    """
    from wuxing.protocols import Artifact, UnitResult

    class WritingRunner:
        emit_event = None

        def __init__(self, ws, seen):
            self._ws = ws
            self._seen = seen

        def run_unit(self, unit_id, domain_id, params,
                     resume_session=None, **kw):
            self._seen[unit_id] = str(params.get("result", ""))
            version = {"F-1": "v1", "F-2": "v2"}.get(unit_id)
            if version is None:
                return UnitResult(unit_id=unit_id, domain_id=domain_id,
                                  status="ok")
            art = Artifact(path="report.md", kind="report",
                           producer_unit=unit_id)
            self._ws.write_artifact(art, version)
            return UnitResult(unit_id=unit_id, domain_id=domain_id, status="ok",
                              artifacts=[art], deliverables=["report.md"])

    o = _mk_orch()
    from wuxing.shared_context import FileCache
    o.file_cache = FileCache()          # 真实现场：引擎必经此缓存
    seen = {}
    o._make_runner = lambda: WritingRunner(o.ws, seen)
    frags = [
        {"fragment_id": "F-1", "domain": "execute", "deps": [],
         "text": "写 v1"},
        {"fragment_id": "F-2", "domain": "execute", "deps": ["F-1"],
         "text": "重写 v2"},
        {"fragment_id": "F-3", "domain": "verify", "deps": ["F-2"],
         "text": "验收"},
    ]
    results = o.run(frags, task_text="汇报")
    assert all(u.status == "ok" for u in results)
    assert "v2" in seen["F-3"], \
        f"F-3 注入必须是最新内容（陈旧缓存回归），实际={seen['F-3']!r}"


def test_pending_dep_does_not_unblock_dependents():
    """真测裁决 W3：挂起（needs_confirm）不满足依赖——下游等待，无依赖碎片照常。"""
    from wuxing.protocols import UnitResult

    class _Runner:
        emit_event = None

        def run_unit(self, unit_id, domain_id, params,
                     resume_session=None, **kw):
            status = "needs_confirm" if unit_id == "A" else "ok"
            return UnitResult(unit_id=unit_id, domain_id=domain_id,
                              status=status)

    o = _mk_orch()
    o._make_runner = lambda: _Runner()
    frags = [
        {"fragment_id": "A", "domain": "execute", "deps": []},
        {"fragment_id": "B", "domain": "execute", "deps": ["A"],
         "require_ok_deps": True},
        {"fragment_id": "C", "domain": "execute", "deps": []},
    ]
    results = o.run(frags, task_text="x")
    st = {r.unit_id: r.status for r in results}
    assert st.get("A") == "needs_confirm"
    assert "B" not in st, "挂起依赖未满足——下游不得启动"
    assert st.get("C") == "ok", "无依赖碎片照常并行"


def test_require_ok_deps_blocks_on_failed_dep():
    """真测裁决 W3：票据语义——依赖票验收未通过（failed/verdict_fail）→ 下游不开工。"""
    from wuxing.protocols import UnitResult

    class _Runner:
        emit_event = None
        def __init__(self, verdict_fail=False):
            self._vf = verdict_fail

        def run_unit(self, unit_id, domain_id, params,
                     resume_session=None, **kw):
            if unit_id == "V":
                return UnitResult(unit_id=unit_id, domain_id=domain_id,
                                  status="ok", verdict_fail=self._vf)
            return UnitResult(unit_id=unit_id, domain_id=domain_id, status="ok")

    # 上游 verify 验收不通过 → 下游不得 ok
    o = _mk_orch()
    o._make_runner = lambda: _Runner(verdict_fail=True)
    frags = [
        {"fragment_id": "V", "domain": "verify", "deps": []},
        {"fragment_id": "E", "domain": "execute", "deps": ["V"],
         "require_ok_deps": True},
    ]
    results = o.run(frags, task_text="x")
    st = {r.unit_id: r.status for r in results}
    assert st.get("V") == "ok"
    assert st.get("E") != "ok", "验收未通过的依赖不得开工"

    # 上游验收通过 → 下游正常开工
    o2 = _mk_orch()
    o2._make_runner = lambda: _Runner(verdict_fail=False)
    results2 = o2.run(frags, task_text="x")
    st2 = {r.unit_id: r.status for r in results2}
    assert st2.get("E") == "ok"


def test_dep_context_skips_empty_deliverable_and_injects_next():
    """真测 REAL-13(b)：空产物跳过（无幽灵路径），继续注入其它真实产物。"""
    from wuxing.protocols import UnitResult

    o = _mk_orch()
    (o.ws.root / "empty.md").write_text("", encoding="utf-8")
    (o.ws.root / "real.md").write_text("真实正文", encoding="utf-8")
    done = {"U-1": UnitResult(unit_id="U-1", domain_id="execute", status="ok",
                              deliverables=["empty.md", "real.md"])}
    _p, text, paths = o._dep_context(done, {"deps": ["U-1"], "domain": "execute"})
    assert "真实正文" in text
    assert "empty.md" not in paths


def test_dep_context_empty_only_deliverable_no_ghost():
    """空产物唯一 → 不注入幽灵条目（路径/正文皆空）。"""
    from wuxing.protocols import UnitResult

    o = _mk_orch()
    (o.ws.root / "empty.md").write_text("", encoding="utf-8")
    done = {"U-1": UnitResult(unit_id="U-1", domain_id="execute", status="ok",
                              deliverables=["empty.md"])}
    _p, text, paths = o._dep_context(done, {"deps": ["U-1"], "domain": "execute"})
    assert paths == "" and text == ""


def test_orchestrator_counts_fragment_attempts():
    """W4.3：碎片启动即计次（attempts 持久化于 task_state，供重试上限裁决）。"""
    o = _mk_orch()
    frags = [{"fragment_id": "F-1", "domain": "plan", "deps": []}]
    o.run(frags, task_text="x")
    assert frags[0].get("attempts") == 1


def test_dep_context_verify_gets_workspace_deliverable_index():
    """P0-1 D（评估方向）：verify 注入附「工作区真实交付物索引」——
    依赖注入可能只有摘要/结果文档，真实代码/数据在工作区（REAL-15/T-2 误杀根因）。"""
    from wuxing.protocols import Artifact, UnitResult
    o = _mk_orch()
    o.ws.write_artifact(Artifact(path="ledger.py", kind="code"), "print(1)")
    o.ws.write_artifact(Artifact(path="test_ledger.py", kind="code"),
                        "def test_x():\n    assert True\n")
    o.ws.write_artifact(Artifact(path="F-T2-result.md", kind="result"),
                        "# 交付摘要")
    done = {"F-T2": UnitResult(unit_id="F-T2", domain_id="execute", status="ok",
                               deliverables=["F-T2-result.md"])}
    _p, text, paths = o._dep_context(
        done, {"fragment_id": "F-T2-v", "domain": "verify", "deps": ["F-T2"]})
    assert "[工作区交付物索引]" in text
    assert "ledger.py" in text and "test_ledger.py" in text
    assert "F-T2-result.md（result）" not in text
    assert "F-T2-result.md" in paths  # 摘要仍按原路径注入（只是不入索引）


def test_dep_context_non_verify_has_no_workspace_index():
    """P0-1 D：索引只给 verify（其余域注入不膨胀）。"""
    from wuxing.protocols import Artifact, UnitResult
    o = _mk_orch()
    o.ws.write_artifact(Artifact(path="ledger.py", kind="code"), "print(1)")
    done = {"F-1": UnitResult(unit_id="F-1", domain_id="execute", status="ok",
                              deliverables=[])}
    _p, text, _paths = o._dep_context(
        done, {"fragment_id": "E-1", "domain": "execute", "deps": ["F-1"]})
    assert "[工作区交付物索引]" not in text


def test_dep_context_user_gets_workspace_deliverable_index():
    """O2-3：user 域也获得「工作区交付物索引」（体验审查需真实交付物视野）。"""
    from wuxing.protocols import Artifact, UnitResult
    o = _mk_orch()
    o.ws.write_artifact(Artifact(path="ledger.py", kind="code"), "print(1)")
    o.ws.write_artifact(Artifact(path="F-T2-result.md", kind="result"),
                        "# 交付摘要")
    done = {"F-T2": UnitResult(unit_id="F-T2", domain_id="execute", status="ok",
                               deliverables=["F-T2-result.md"])}
    _p, text, _paths = o._dep_context(
        done, {"fragment_id": "F-T2-u", "domain": "user", "deps": ["F-T2"]})
    assert "[工作区交付物索引]" in text
    assert "ledger.py" in text
