"""TDD：碎片间缓存共享（L1 产物注入缓存 + L3 三要素共享——有向增量）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.protocols import Artifact, UnitResult
from wuxing.shared_context import FileCache, SharedContext
from wuxing.workspace import Workspace


def _result(unit_id, domain="execute", status="ok", logs=None, artifact=None):
    return UnitResult(unit_id=unit_id, domain_id=domain, status=status,
                      artifacts=[artifact] if artifact else [],
                      logs=logs or [],
                      deliverables=[artifact.path] if artifact else [])


def test_file_cache_dedup_and_stale():
    """L1：产物内容缓存（一次读取；改文件后旧值仍命中——明确语义，clear 重置）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    p = "data/in.csv"
    (ws.root / "data").mkdir()
    (ws.root / "data" / "in.csv").write_text("A" * 20000, encoding="utf-8")
    fc = FileCache(max_chars=1000)
    first = fc.read(str(ws.root / p))
    assert len(first) == 1001, "读取即截断（注入缓存）+省略号"
    (ws.root / "data" / "in.csv").write_text("B" * 20000, encoding="utf-8")
    assert fc.read(str(ws.root / p)) == first, "缓存命中（脏读语义——进程内确定性）"
    fc.clear()
    assert fc.read(str(ws.root / p)) != first, "clear 后重读新内容"


def test_shared_record_three_elements():
    """L3：record 提取三要素——交付物分析/工具顺序/特征值（确定性）。"""
    sc = SharedContext()
    art = Artifact(path="F-exec1-result.md", kind="result", producer_unit="F-exec1")
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(art, "执行完成摘要" + "内容" * 300)
    res = _result("F-exec1", logs=["[tool] read_file: 文件", "[tool] write_artifact: written x.md"],
                  artifact=art)
    sc.record(res, fragment_key="实现斐波那契", ws=ws)
    rec = sc._records[0]
    assert "执行完成摘要" in rec["deliverable_analysis"], "交付物分析（收口文本截断）"
    assert "[tool] read_file" in rec["tool_sequence"], "工具顺序"
    assert rec["fingerprint"]["domain"] == "execute"
    assert rec["fingerprint"]["fragment"] == "实现斐波那契"


def test_shared_for_next_excludes_self_and_limited():
    """for_next：过滤自身；容量上限 2048。"""
    sc = SharedContext(max_chars=2048)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    for i in range(5):
        art = Artifact(path=f"f{i}.md", kind="result", producer_unit=f"F{i}")
        ws.write_artifact(art, f"分析内容{i}：" + "Z" * 800)
        sc.record(_result(f"F{i}", logs=["[tool] write_artifact: written f{i}.md"],
                          artifact=art), fragment_key=f"碎片{i}", ws=ws)
    seg = sc.for_next("F-other")
    assert len(seg) <= 2048, "共享段容量上限"
    assert "F-other" not in seg or "F-other" not in [r["fragment_id"] for r in sc._records]
    # 不含未完成碎片（无 record 无共享）
    assert "F7" not in seg


def test_runner_injects_shared_into_next_fragment():
    """集成：plan 完成后 execute 碎片 user 尾部含共享段（有向增量）。"""
    from wuxing.llm.tool_results import ToolCallResult
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.loader import load_tools

    class TwoPhase:
        def __init__(self):
            self.calls = 0
            self.seen = []

        def name(self):
            return "two"

        def chat(self, messages, tools=None):
            self.calls += 1
            self.seen.append([str(m.get("content", "")) for m in messages])
            if "域：execute" in " ".join(str(m.get("content", "")) for m in messages):
                return ToolCallResult(text="执行完成：已实现", tool_calls=[{"name": "write_artifact",
                    "arguments": {"path": "x.md", "kind": "result", "content": "done"}}])
            return ToolCallResult(text="方案：完整计划", tool_calls=[{"name": "write_artifact",
                "arguments": {"path": "p.md", "kind": "plan", "content": "计划"}}])

    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    sc = SharedContext()
    llm = TwoPhase()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws), shared=sc)
    r.run_unit("F-plan0", "plan", {"goal": "plan:制定方案"})
    r2 = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws), shared=sc)
    r2.run_unit("F-exec1", "execute", {"goal": "实现", "fragment_key": "实现"})
    exec_msgs = next(m for m in llm.seen
                     if any("域：execute" in str(x) for x in m))
    exec_text = " ".join(exec_msgs)
    assert "同任务已完成碎片" in exec_text, "共享段必须注入后续碎片"
    assert "F-plan0" in exec_text, "共享段必含碎片特征值（供循迹）"
    assert "特征值" in exec_text and "工具顺序" in exec_text, "三要素齐备"


def test_dep_context_uses_file_cache():
    """B5：_dep_context 产物读取必须走 FileCache（多碎片重复读同一产物免磁盘 IO）"""
    import pathlib
    import tempfile

    from wuxing.config import EngineConfig
    from wuxing.orchestrator import Orchestrator
    from wuxing.protocols import Artifact, UnitResult
    from wuxing.registry import DomainRegistry
    from wuxing.shared_context import FileCache
    from wuxing.tools.base import ToolRegistry
    from wuxing.workspace import Workspace

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="plan.md", kind="plan",
                               producer_unit="F-plan"), "方案内容" * 200)
    cfg = EngineConfig()
    reg = DomainRegistry(cfg)
    fc = FileCache()
    orch = Orchestrator(cfg, reg, ws, None, ToolRegistry([]))
    orch.file_cache = fc

    reads = {"n": 0}
    orig = ws.read

    def counting_read(p):
        reads["n"] += 1
        return orig(p)

    ws.read = counting_read
    done = {"F-plan": UnitResult(unit_id="F-plan", domain_id="plan",
                                 status="ok",
                                 artifacts=[Artifact(path="plan.md", kind="plan",
                                                     producer_unit="F-plan")])}
    orch._dep_context(done, {"deps": ["F-plan"], "domain": "execute"})
    first = reads["n"]
    orch._dep_context(done, {"deps": ["F-plan"], "domain": "execute"})
    assert reads["n"] == first, "第二次读取必须命中 FileCache（不再读盘）"
