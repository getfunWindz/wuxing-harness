"""真测裁决 W2：动态轮数——基线到达不失败（机械评分 + 自评），安全上限才硬停。

用户裁决（2026-09-26）：轮数只是基础值，不限制模型工作；机械评分、模型自评
完成逻辑闭环；安全上限才是硬约束。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.tool_results import ToolCallResult
from wuxing.protocols import Artifact
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class _Scripted:
    def __init__(self, outs):
        self._outs = list(outs)
        self.calls = 0

    def name(self):
        return "scripted"

    def chat(self, messages, tools=None):
        self.calls += 1
        out = self._outs.pop(0) if self._outs else ""
        return out() if callable(out) else out


def _mk(llm, **kw):
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2,
                       max_loop_rounds_hard=6, max_unit_budget_hard=6, **kw)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="result.md", kind="result",
                               producer_unit="F-x"), "待验产物内容")
    return Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))


def test_dynamic_rounds_continue_after_baseline():
    """基线（2 轮）到达不失败：自评轮后第 3 轮收敛 → ok（旧行为 failed）。"""
    llm = _Scripted([
        ToolCallResult(text="", tool_calls=[
            {"name": "read_dependency", "arguments": {"path": "result.md"}}]),
        "",  # 基线到达轮：无文本无工具 → 注入收敛自评
        ToolCallResult(text="结论：通过", tool_calls=[
            {"name": "write_artifact",
             "arguments": {"path": "v.md", "kind": "verdict",
                           "content": "结论：通过"}}]),
    ])
    r = _mk(llm)
    res = r.run_unit("U-1", "verify", {"result": "待验产物"})
    assert res.status == "ok", f"基线后应可继续收敛：{res.error}"
    assert llm.calls == 3


def test_dynamic_rounds_stall_fails_fast():
    """基线后连续 2 轮无进展（无写物证）→ stalled 失败（不烧到安全上限）。"""
    llm = _Scripted(["", "", "", "", "", ""])
    r = _mk(llm)
    res = r.run_unit("U-1", "verify", {"result": "待验产物"})
    assert res.status == "failed"
    assert "stalled" in (res.error or ""), res.error
    assert llm.calls < 6, f"停滞应在安全上限前停止（实际 {llm.calls}）"


def test_dynamic_rounds_safety_cap_still_fails():
    """持续有进展但不收敛 → 安全上限硬停（文案区别于旧 budget/rounds exhausted）。"""
    counter = {"n": 0}

    def _next():
        counter["n"] += 1
        return ToolCallResult(text="继续", tool_calls=[
            {"name": "write_artifact",
             "arguments": {"path": f"r{counter['n']}.md", "kind": "verdict",
                           "content": "继续"}}])

    llm = _Scripted([_next] * 10)
    r = _mk(llm)
    res = r.run_unit("U-1", "verify", {"result": "待验产物"})
    assert res.status == "failed"
    # S1-B：文案改为诚实收敛（预算耗尽——……）
    assert "预算耗尽" in (res.error or ""), res.error
    assert llm.calls == 6, f"应在安全上限停止（实际 {llm.calls}）"


def test_baseline_prompt_keeps_existing_behavior_below_baseline():
    """基线内收敛路径不回归：第 1 轮即收敛 → ok。"""
    llm = _Scripted([
        ToolCallResult(text="结论：通过", tool_calls=[
            {"name": "read_dependency", "arguments": {"path": "result.md"}},
            {"name": "write_artifact",
             "arguments": {"path": "v.md", "kind": "verdict",
                           "content": "结论：通过"}}]),
    ])
    r = _mk(llm)
    res = r.run_unit("U-1", "verify", {"result": "待验产物"})
    assert res.status == "ok" and llm.calls == 1


def test_hard_caps_must_be_ge_baseline():
    """配置校验：安全上限 < 基线 → 报错（早报）。"""
    from wuxing.config_schema import validate_config

    errs = validate_config({"max_loop_rounds": 6, "max_loop_rounds_hard": 3,
                            "max_unit_budget": 5, "max_unit_budget_hard": 2})
    assert errs, "hard < baseline 必须校验失败"
    assert validate_config({"max_loop_rounds": 6, "max_loop_rounds_hard": 12,
                            "max_unit_budget": 5, "max_unit_budget_hard": 12}) == []


def test_stalled_failure_classified_as_budget():
    """归因：stalled 属收敛类（budget/收敛修复），不落 unknown。"""
    from wuxing.repairer import classify_failure

    assert classify_failure("guard: stalled (no progress)") == "budget"
    assert classify_failure("guard: safety cap reached (budget)") == "budget"
