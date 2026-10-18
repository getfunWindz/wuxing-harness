"""TDD · O2-2 P2：旧快照替换（投影层 keep-latest，防上下文膨胀）。

设计：`docs/WUXING_内置浏览器体验断言_设计_2026-10-07.md` §4.2（Gemini
snapshotSuperseder 先例）。纪律：仅注入投影（存档零改写——G3）。
"""
import pathlib

from wuxing.llm.tool_results import ToolCallResult
from wuxing.protocols import Tool, ToolResult
from wuxing.snapshot_supersede import supersede_old_snapshots


def _env(text: str) -> str:
    return f'<tool_result source="browser_snapshot">\n{text}\n</tool_result>'


# ---- 纯函数 ----


def test_keep_latest_single_message():
    msgs = [{"role": "user", "content": f"{_env('OLD-A')}\n{_env('NEW-B')}"}]
    n = supersede_old_snapshots(msgs)
    assert n == 1
    content = msgs[0]["content"]
    assert "[旧快照已被替换]" in content
    assert "OLD-A" not in content
    assert "NEW-B" in content
    assert supersede_old_snapshots(msgs) == 0, "幂等：二次调用不重复计数"


def test_keep_latest_across_messages_and_untouched_others():
    msgs = [
        {"role": "system", "content": _env("SYS-KEEP")},
        {"role": "user", "content": "hello"},
        {"role": "user", "content": _env("OLD")},
        {"role": "user",
         "content": '<tool_result source="read_file">\nKEEP\n</tool_result>'},
        {"role": "user", "content": _env("NEW")},
    ]
    n = supersede_old_snapshots(msgs)
    assert n == 1
    assert "SYS-KEEP" in msgs[0]["content"]      # system 不处理
    assert "OLD" not in msgs[2]["content"]
    assert "KEEP" in msgs[3]["content"]          # 其他工具零改动
    assert "NEW" in msgs[4]["content"]


def test_no_snapshot_returns_zero():
    msgs = [{"role": "user", "content": "plain"}]
    assert supersede_old_snapshots(msgs) == 0
    assert msgs[0]["content"] == "plain"


def test_legacy_line_form():
    msgs = [
        {"role": "user",
         "content": '[tool] browser_snapshot: - button "a" [ref=e1]\n- link "b"'},
        {"role": "user",
         "content": '[tool] browser_snapshot: - button "c" [ref=e2]'},
    ]
    n = supersede_old_snapshots(msgs)
    assert n == 1
    assert msgs[0]["content"] == "[tool] browser_snapshot: [旧快照已被替换]"
    assert "e2" in msgs[1]["content"]


def test_legacy_marker_inside_envelope_not_touched():
    """页面文本混入伪 legacy 标记（信封内）——不得二次替换/破坏。"""
    inner = "[tool] browser_snapshot: 页面里的假标记\n真实内容"
    msgs = [{"role": "user", "content": _env(inner)}]
    assert supersede_old_snapshots(msgs) == 0
    assert "真实内容" in msgs[0]["content"]


# ---- runner 级（轮内到达 + resume 投影） ----


class ScriptedLlm:
    def __init__(self, outs):
        self.outs = list(outs)

    def name(self):
        return "scripted"

    def spec(self):
        return "mock"

    def chat(self, messages, tools=None):
        if self.outs:
            return self.outs.pop(0)
        return ToolCallResult(text="验收完成：任务已完成", tool_calls=[])


class SnapTool(Tool):
    """假 browser_snapshot（计数内容——便于断言新旧块）。"""

    def __init__(self):
        self.n = 0

    def name(self):
        return "browser_snapshot"

    def description(self):
        return "fake snapshot"

    def input_schema(self):
        return {"type": "object", "properties": {}}

    def permission(self):
        return {"read": True, "write": False, "execute": True,
                "network": True, "destructive": False}

    def execute(self, **kw):
        self.n += 1
        return ToolResult(status="ok", tool_name=self.name(),
                          content=f"- fake snapshot {self.n}")


def _snap_call():
    return {"name": "browser_snapshot", "arguments": {}}


def _snap_runner(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.base import ToolRegistry
    from wuxing.tools.builtin import BUILTIN_TOOLS
    from wuxing.trace import TraceLogger
    from wuxing.workspace import Workspace
    cfg = EngineConfig(confirm_threshold=0.0, max_loop_rounds=5,
                       max_unit_budget=7)
    ws = Workspace(pathlib.Path(tmp_path))
    trace = TraceLogger(pathlib.Path(tmp_path) / ".wuxing" / "trace.jsonl")
    reg = DomainRegistry(cfg)
    reg.activate(["user"])
    tools = ToolRegistry(BUILTIN_TOOLS(ws) + [SnapTool()])
    return Runner(cfg, reg, ws, None, tools, confirm_gate=None,
                  auto_confirm=True, trace=trace), trace


def test_runner_supersedes_old_snapshot_in_rounds(tmp_path):
    llm = ScriptedLlm([
        ToolCallResult(text="", tool_calls=[_snap_call()]),
        ToolCallResult(text="", tool_calls=[_snap_call()]),
        ToolCallResult(text="验收完成：页面已核查", tool_calls=[]),
    ])
    r, trace = _snap_runner(tmp_path)
    r.llm = llm
    res = r.run_unit("F-1", "user",
                     {"goal": "核查本地页面", "plan": "p"})
    assert res.status == "ok", res.error
    joined = "\n".join(str(m.get("content", "")) for m in r._messages)
    assert "fake snapshot 1" not in joined, "旧快照块应被替换"
    assert "fake snapshot 2" in joined, "最新快照必须保留"
    assert "[旧快照已被替换]" in joined
    rows = [x for x in trace.load()
            if x.get("event") == "snapshot_superseded"]
    assert rows and rows[-1]["replaced"] == 1


def test_build_messages_supersedes_on_resume(tmp_path):
    r, _ = _snap_runner(tmp_path)
    msgs, _sizes, _src = r._build_unit_messages(
        "U-1", "prompt", "sys", conv_name=None,
        resume_session=[{"role": "user", "content": _env("OLD")},
                        {"role": "user", "content": _env("NEW")}],
        continue_from=None, skill_index_msg=None, ext_seg_msg=None,
        pure=True, domain_id="user")
    assert "[旧快照已被替换]" in msgs[0]["content"]
    assert "NEW" in msgs[1]["content"]
