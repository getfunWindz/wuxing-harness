"""TDD · O2-3：user 域体验审查能力（read 接线 / 索引注入 / verify run_tests 提示 / 行为级）。

设计：docs/WUXING_user域体验审查_设计_2026-10-07.md（§2 改动点；§4 验收）。
"""
import json
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.domains.defaults import DEFAULT_DOMAINS
from wuxing.llm.tool_results import ToolCallResult
from wuxing.protocols import Artifact
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.trace import TraceLogger
from wuxing.workspace import Workspace


def test_user_domain_whitelist_has_read_tools():
    """user 域可核查交付物：白名单含 4 个 read 工具（run_tests 既有能力保留）。"""
    wl = DEFAULT_DOMAINS["user"].tool_whitelist
    for name in ("read_file", "read_dependency", "glob", "grep"):
        assert name in wl, f"user 域缺 {name}"
    assert "run_tests" in wl


def test_user_domain_quality_notes_require_actual_review():
    """user 契约要求「实际核查 + 证据」，不得只写标准。"""
    notes = DEFAULT_DOMAINS["user"].quality_notes
    assert "核查" in notes
    assert "证据" in notes
    assert "实际" in notes


def test_user_domain_skeleton_has_paths_and_review_instruction():
    """skeleton 引用 {paths} 并指令先核查后写审查文档。"""
    sk = DEFAULT_DOMAINS["user"].prompt_skeleton
    assert "{paths}" in sk
    assert "核查" in sk


def test_user_unit_read_then_write_records_read_tool_call():
    """行为级：user 单元先 read 后写审查文档 → 收敛且 trace 可见 read 工具调用。"""
    class ReadThenWrite:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "readwrite"

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return ToolCallResult(text="先核查交付物", tool_calls=[
                    {"name": "read_file",
                     "arguments": {"path": "out.md"}}])
            return ToolCallResult(
                text="验收标准：功能完整、体验流畅",
                tool_calls=[{"name": "write_file",
                             "arguments": {
                                 "path": "user/审查.md",
                                 "content": "验收标准：功能完整\n"
                                            "实际发现：已实现\n"
                                            "证据：读了 out.md\n"
                                            "结论：通过"}}])

    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="out.md", kind="result",
                               producer_unit="F-1"), "实现内容")
    trace = TraceLogger(ws.root / "trace.jsonl")
    reg = DomainRegistry(cfg)
    reg.activate(["user"])  # 条件域：模拟任务启用场景
    r = Runner(cfg, reg, ws, ReadThenWrite(), load_tools(ws), trace=trace)
    res = r.run_unit("U-1", "user", {"goal": "审查交付物的用户体验"})
    assert res.status == "ok", f"read+write+markers 应收敛：{res.error}"
    rows = [json.loads(x) for x in
            (ws.root / "trace.jsonl").read_text(
                encoding="utf-8").splitlines() if x.strip()]
    calls = [row for row in rows if row.get("event") == "tool_call"
             and row.get("unit_id") == "U-1"]
    names = [str(row.get("name", "")) for row in calls]
    assert "read_file" in names, f"trace 须含 read_file 调用：{names}"
    read_row = calls[names.index("read_file")]
    assert read_row.get("status") == "ok", "read 调用不得被白名单拦截"


def test_verify_prompt_mentions_run_tests():
    """verify 提示补 run_tests 证据指引（O2-3 §2.3；判定契约不变）。"""
    d = DEFAULT_DOMAINS["verify"]
    joined = d.quality_notes + "\n" + d.prompt_skeleton
    assert "run_tests" in joined


# ---- O2-2 P1 T7：user 域浏览器接线（作业面边界） ----


def test_user_domain_whitelist_has_browser_tools():
    """user 域可做界面体验审查：白名单含浏览器三工具。"""
    wl = DEFAULT_DOMAINS["user"].tool_whitelist
    for name in ("browser_navigate", "browser_snapshot",
                 "browser_screenshot"):
        assert name in wl, f"user 域缺 {name}"


def test_user_domain_quality_notes_mention_browser_inspection():
    """user 契约含浏览器核查指引（可交互界面 + 快照证据）。"""
    notes = DEFAULT_DOMAINS["user"].quality_notes
    assert "可交互界面" in notes
    assert "快照" in notes


def test_browser_tools_are_user_only():
    """首期边界：浏览器工具仅 user 域（plan/execute/verify 不含）。"""
    for d in ("plan", "execute", "verify"):
        wl = DEFAULT_DOMAINS[d].tool_whitelist
        assert not any(str(n).startswith("browser_") for n in wl), d


# ---- O2-2 P2：操作面接线 ----


def test_user_domain_whitelist_has_browser_action_tools():
    """user 域操作面：白名单含 click/type/wait。"""
    wl = DEFAULT_DOMAINS["user"].tool_whitelist
    for name in ("browser_click", "browser_type", "browser_wait"):
        assert name in wl, f"user 域缺 {name}"


def test_user_domain_quality_notes_mention_interaction():
    """可交互界面指引升级：必要时真实互动（click/type）后再快照。"""
    notes = DEFAULT_DOMAINS["user"].quality_notes
    assert "互动" in notes


def test_user_domain_whitelist_has_evaluate():
    """O2-2 P3：evaluate 显式档——白名单静态含名（注册受双闸控制）。"""
    assert "browser_evaluate" in DEFAULT_DOMAINS["user"].tool_whitelist
