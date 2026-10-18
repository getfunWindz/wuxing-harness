"""delegate 工具（3c：子智能体委托 + 溯源链 parent 链接 + 深度/预算护栏）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.mock import MockLlmProvider
from wuxing.provenance import ProvenanceLedger
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.tools.delegate import DelegateTool
from wuxing.workspace import Workspace


def _mk_sub_runner(ws, reg, goal, domain):
    r = Runner(EngineConfig(), reg, ws, MockLlmProvider(), BUILTIN_TOOLS(ws))
    r._delegate_domain = domain or "plan"
    return r


def test_delegate_ok_returns_summary_and_artifacts():
    ledger = ProvenanceLedger(pathlib.Path(tempfile.mkdtemp()) / "p.jsonl")
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = DomainRegistry(EngineConfig())
    calls = {"n": 0}
    def factory(goal, domain=None):
        calls["n"] += 1
        return _mk_sub_runner(ws, reg, goal, domain), (lambda: None)
    t = DelegateTool(factory, ledger=ledger, parent_unit_id="F-1")
    res = t.execute(goal="制定任务方案", domain="plan")
    assert res.status == "ok"
    assert "-> ok" in res.content
    # 溯源：父链 parent_id=F-1，子任务记录存在
    rows = ledger.load()
    assert any(r["parent_id"] == "F-1" and r["status"] == "ok" for r in rows)
    assert calls["n"] == 1


def test_delegate_depth_guard_rejects():
    """深度 2：二阶委托被拒（factory 返回 None → error 非崩溃）。"""
    Workspace(pathlib.Path(tempfile.mkdtemp()))
    DomainRegistry(EngineConfig())
    def factory(goal, domain=None):
        return None  # 模拟深度护栏拒绝
    t = DelegateTool(factory)
    res = t.execute(goal="再委托")
    assert res.status == "error"
    assert "护栏" in (res.error or "")


def test_delegate_budget_inherit_child_calls():
    """预算继承：子任务调用数上报（父单元扣除口径）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = DomainRegistry(EngineConfig())
    def factory(goal, domain=None):
        sub = _mk_sub_runner(ws, reg, goal, domain)
        return sub, (lambda: None)
    t = DelegateTool(factory)
    res = t.execute(goal="写个方案", domain="plan")
    assert res.child_calls >= 1  # mock 路径至少 1 次调用


# ============================== L0-3 深度计数正确性 ==========================
import threading
import time
from types import SimpleNamespace


class _SlowRunner:
    """伪子 runner：sleep 模拟真实委托耗时（并发窗口放大竞态）。"""

    def __init__(self, n, sleep=0.15, boom=False):
        self._n = n
        self._sleep = sleep
        self._boom = boom
        self._calls = 1
        self._delegate_domain = "plan"

    def run_unit(self, *a, **kw):
        if self._boom:
            raise RuntimeError(f"boom-{self._n}")
        time.sleep(self._sleep)
        return SimpleNamespace(status="ok", artifacts=[], logs=[],
                               error="", unit_id=f"delegate-{self._n}")


class _HoldRunner:
    """伪子 runner：持槽直到收到释放信号（配合拒绝事件——确定性口径）。"""

    def __init__(self, n, release: threading.Event):
        self._n = n
        self._release = release
        self._calls = 1
        self._delegate_domain = "plan"

    def run_unit(self, *a, **kw):
        self._release.wait(timeout=5)  # 持槽等待（父测试收集到两个拒绝后释放）
        return SimpleNamespace(status="ok", artifacts=[], logs=[],
                               error="", unit_id=f"delegate-{self._n}")


def test_delegate_concurrent_depth_guard():
    """L0-3 并发护栏：同一时刻活跃委托深度 ≤2（P16 并行碎片同时 delegate）。

    确定性口径（技术债收口 2026-09-12 改写）：被放行的两个持槽不释放；
    其余必须**立即被拒**（信号量计数）——不依赖 sleep 时序；护栏若失效
    （全放行）则收不到拒绝→断言确定性失败。
    """
    DomainRegistry(EngineConfig())
    release = threading.Event()
    rejected = threading.Semaphore(0)
    counter = {"i": 0, "lock": threading.Lock()}

    def factory(goal, domain=None):
        with counter["lock"]:
            counter["i"] += 1
            i = counter["i"]
        return _HoldRunner(i, release), (lambda: None)

    t = DelegateTool(factory)
    results = []

    def run():
        r = t.execute(goal="g")
        results.append(r)
        if r.status != "ok":
            rejected.release()

    threads = [threading.Thread(target=run) for _ in range(4)]
    for th in threads:
        th.start()
    got1 = rejected.acquire(timeout=3)
    got2 = rejected.acquire(timeout=3) if got1 else False
    release.set()  # 无论如何释放——防死锁
    for th in threads:
        th.join(timeout=5)
    oks = [r for r in results if r.status == "ok"]
    assert got1 and got2, "护栏必须拒绝超限委托（未收到拒绝信号——可能全放行）"
    assert len(oks) == 2, f"恰放行 2 个（实际 {len(oks)}）"
    assert len(results) == 4, f"四线程均须有结果（实际 {len(results)}）"


def test_delegate_exception_releases_depth():
    """L0-3 异常路径：子执行抛异常 → 深度计数释放（不漏）。

    无 finally（审查 B1）：异常穿越 execute → 计数永久泄漏 → 后续委托被拒。
    断言：异常后连续 3 次 execute 均不被「深度护栏」拒绝。
    """
    DomainRegistry(EngineConfig())
    state = {"boom": True}
    def factory(goal, domain=None):
        if state["boom"]:
            return _SlowRunner(0, boom=True), (lambda: None)
        return _SlowRunner(0, sleep=0.01), (lambda: None)
    t = DelegateTool(factory)
    # 真实路径：ToolRegistry.execute 捕获异常包装为 ToolResult（深度仍须释放）
    def guarded():
        try:
            return t.execute(goal="g")
        except RuntimeError as e:
            return SimpleNamespace(status="error", error=str(e))
    first = guarded()
    assert first.status == "error", "异常应转化为结构化 error"
    state["boom"] = False
    for i in range(3):
        r = guarded()
        assert "深度" not in (r.error or ""), \
            f"第 {i + 1} 次执行被深度护栏拒绝（计数泄漏）"


def test_delegate_subtask_traced():
    """A7：delegate 子任务必须产生 trace 事件（llm_call/tool_call 按子 unit_id）——
    评测原料完整（与 child_calls 预算计数口径一致）。"""
    import pathlib
    import tempfile

    from wuxing.engine import Engine

    class DelegateLlm:
        def __init__(self):
            self.usage_history = []
            self.call_count = 0

        def name(self):
            return "dl"

        def spec(self):
            return "dl"

        def supports_native_tools(self):
            return False

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.usage_history.append({"input": 5, "output": 5,
                                       "cache_read": 0, "cache_write": 0})
            self.call_count += 1
            text = " ".join(m.get("content", "") for m in messages)
            if "域：plan" in text or "制定" in text:
                # 子任务（规划域）：产出方案
                return ToolCallResult(
                    text="方案：步骤1、步骤2",
                    tool_calls=[{"name": "write_artifact",
                                 "arguments": {"path": "sub-plan.md",
                                               "kind": "plan",
                                               "content": "方案：步骤1、步骤2"}}])
            if self.call_count == 1:
                # 主单元第一轮：委托
                return ToolCallResult(
                    text="委托子智能体制定方案",
                    tool_calls=[{"name": "delegate",
                                 "arguments": {"goal": "制定简单方案",
                                               "domain": "plan"}}])
            return ToolCallResult(
                text="执行完成：委托完毕",
                tool_calls=[{"name": "write_artifact",
                             "arguments": {"path": "out.md", "kind": "result",
                                           "content": "完成"}}])

    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), llm=DelegateLlm(),
                 auto_confirm=True)
    res = eng.orchestrator.runner.run_unit(
        "F-m", "execute",
        {"goal": "实现并验证登录", "task": "实现并验证登录", "plan": "步骤1",
         "result": "", "paths": "", "fragment_key": "实现并验证登录"})
    assert res.status == "ok", res.error
    rows = eng.trace.load()
    sub_events = [r for r in rows
                  if str(r.get("unit_id", "")).startswith("delegate-")]
    assert sub_events, f"子任务必须产生 trace 事件：{rows}"
    assert any(r["event"] == "llm_call" for r in sub_events), \
        "子任务的 LLM 调用必须进 trace（评测原料）"
    assert any(r["event"] == "tool_call" for r in sub_events), \
        "子任务的工具调用必须进 trace（评测原料）"


def test_delegate_subtask_gets_deliverable_semantics():
    """D1：delegate 子任务必须注入交付物类型语义（与主碎片 L4 修复对齐）——
    子任务「不知交付类型→探索不止」同病：params.deliverables 按目标域注入。"""
    import pathlib
    import tempfile

    from wuxing.engine import Engine

    class D1Llm:
        def __init__(self):
            self.usage_history = []
            self.call_count = 0
            self.histories = []  # 每轮消息快照（子任务执行完整可查）

        def name(self):
            return "d1"

        def spec(self):
            return "d1"

        def supports_native_tools(self):
            return False

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.usage_history.append({"input": 5, "output": 5,
                                       "cache_read": 0, "cache_write": 0})
            self.call_count += 1
            self.histories.append(list(messages))
            text = " ".join(m.get("content", "") for m in messages)
            if "域：plan" in text:
                return ToolCallResult(text="方案：步骤", tool_calls=[
                    {"name": "write_artifact", "arguments": {
                        "path": "sub-plan.md", "kind": "plan",
                        "content": "方案"}}])
            if self.call_count == 1:
                return ToolCallResult(text="委托", tool_calls=[
                    {"name": "delegate", "arguments": {
                        "goal": "制定简单方案", "domain": "plan"}}])
            return ToolCallResult(text="执行完成", tool_calls=[
                {"name": "write_artifact", "arguments": {
                    "path": "out.md", "kind": "result", "content": "x"}}])

    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), llm=D1Llm(),
                 auto_confirm=True)
    eng.orchestrator.runner.run_unit(
        "F-m", "execute",
        {"goal": "实现任务", "task": "实现任务", "plan": "步骤",
         "result": "", "paths": "", "fragment_key": "实现任务"})
    # 子任务 prompt（user 消息）必须含交付物类型（plan 域 → plan）
    joined = "\n".join(
        m.get("content", "")
        for hist in eng.llm.histories for m in hist
        if m.get("role") == "user")
    assert "本片段交物" in joined or "本碎片交付物类型" in joined, \
        f"子任务必须注入交付物类型语义（与主碎片对齐）：{joined[-300:]}"


def test_delegate_sub_runner_inherits_mcp_and_sandbox(monkeypatch, tmp_path):
    """B5（技术债收口 2026-09-12）：delegate 子 Runner 工具装载必须继承
    引擎的 MCP 配置与沙箱参数（此前 ToolLoaderConfig() 空置——子任务无 MCP、无沙箱）。"""
    import wuxing.engine as emod
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine

    eng = Engine(cfg=EngineConfig(), workdir=tmp_path, auto_confirm=True)
    eng._mcp_cfgs = ["FAKE-CFG"]  # 白盒：验证透传，无需真实 MCP server
    captured = {}
    real_load = emod.load_tools
    from wuxing.tools.loader import ToolLoaderConfig

    def _capture(ws, cfg=None, **kw):
        captured["cfg"] = cfg
        captured["kw"] = kw
        # 仅捕获（不将假配置传真实加载器——避免触发 MCP 连接路径）
        return real_load(ws, ToolLoaderConfig(), skills=kw.get("skills"))

    monkeypatch.setattr(emod, "load_tools", _capture)
    eng._delegate_runner("子任务")
    assert captured["cfg"].mcp_servers == ["FAKE-CFG"], captured
    assert captured["kw"].get("sandbox_enabled") is True, captured
    assert "mcp_pool" in captured["kw"], captured


# ============================== E3-1/R4（CU2）：只读派生 ==========================

def test_delegate_read_only_kw_passed_to_factory():
    """E3-1/R4：read_only=True 透传工厂（工具层协议）；缺省路径不传（旧工厂兼容）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = DomainRegistry(EngineConfig())
    captured = {}

    def factory(goal, domain=None, read_only=False):
        captured["read_only"] = read_only
        return _mk_sub_runner(ws, reg, goal, domain), (lambda: None)

    t = DelegateTool(factory)
    res = t.execute(goal="只读勘察", read_only=True)
    assert res.status == "ok"
    assert captured["read_only"] is True

    calls = {"n": 0}

    def factory2(goal, domain=None):
        calls["n"] += 1
        return _mk_sub_runner(ws, reg, goal, domain), (lambda: None)

    t2 = DelegateTool(factory2)
    assert t2.execute(goal="常规子任务").status == "ok"
    assert calls["n"] == 1  # 缺省不传 read_only（旧两参工厂兼容）


def test_delegate_read_only_filters_write_tools(tmp_path):
    """E3-1/R4：Engine 只读派生——子工具集走 read-only 剖面（无写/执行类工具）。"""
    from wuxing.engine import Engine

    eng = Engine(cfg=EngineConfig(use_real_shape=False),
                 workdir=pathlib.Path(tmp_path), auto_confirm=True)
    sub, _rel = eng._delegate_runner("只读勘察", "execute", read_only=True)
    names = {t.name() for t in sub.tools.list()}
    assert "read_file" in names
    assert "bash" not in names and "write_file" not in names
    assert "write_artifact" not in names

    sub2, _rel2 = eng._delegate_runner("常规子任务", "execute")
    names2 = {t.name() for t in sub2.tools.list()}
    assert "bash" in names2 and "write_file" in names2  # 缺省行为不变（workspace-write）
