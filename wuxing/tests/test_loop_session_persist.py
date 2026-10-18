"""TDD：P4 T2 执行会话持久化（append-only jsonl——消息级回放材料）。"""
import json
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.tool_results import ToolCallResult
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class TwoRoundLlm:
    def __init__(self):
        self.calls = 0

    def name(self):
        return "tworound"

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return ToolCallResult(text="我先检查依赖", tool_calls=[
                {"name": "read_dependency",
                 "arguments": {"path": "no_such.md"}}])
        return "方案：完整执行计划"


def _session_path(ws, unit_id="U-1"):
    return ws.root / ".wuxing" / "sessions" / f"{unit_id}.jsonl"


def test_session_log_written_per_round():
    """run_unit 后 session jsonl 存在；每轮（含 final）都有记录——可回放。"""
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = TwoRoundLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok"
    p = _session_path(ws)
    assert p.exists(), "会话文件必须落盘"
    lines = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) >= 2, f"每轮需有记录：{len(lines)}"
    rounds = [l.get("round") for l in lines]
    assert 1 in rounds and 2 in rounds, f"轮次记录完整：{rounds}"
    # 消息内容可回放（第一轮含系统消息）
    assert any("域：plan" in str(m.get("content", "")) for l in lines
               for m in l.get("messages", []))
    # final 状态留档
    assert lines[-1].get("state") in ("done", "ok"), f"末条应含终态：{lines[-1]}"


class PureToolRoundLlm:
    """第一轮纯工具调用（无文本）——Moonshot 拒绝空 content 消息（真跑 2026-10-04）。"""
    def __init__(self):
        self.calls = 0

    def name(self):
        return "puretools"

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return ToolCallResult(text="", tool_calls=[
                {"name": "glob", "arguments": {"pattern": "*.md"}}])
        return "方案：完成"


def test_pure_tool_round_no_empty_message():
    """纯工具轮（模型无文本）不得向历史/会话追加空 content 消息。

    根因（E3-4 真跑 2026-10-04）：Kimi k3 对空 content 返回 400
    （the message ... must not be empty）→ verify 单元 provider_error。
    GLM/MiMo 容忍但入历史也是脏数据——无信号。"""
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, PureToolRoundLlm(), load_tools(ws))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok"
    empties = [m for m in r._messages
               if m.get("role") == "user" and not str(m.get("content") or "").strip()]
    assert not empties, f"空消息不得入历史：{empties}"
    lines = [json.loads(l) for l in
             _session_path(ws).read_text(encoding="utf-8").splitlines() if l.strip()]
    for line in lines:
        for m in line.get("messages", []):
            if m.get("role") == "user":
                assert str(m.get("content") or "").strip(), \
                    f"session 空消息（round={line.get('round')}）"
    # 工具结果仍在（信号不丢）
    assert any("tool_result" in str(m.get("content", "")) for m in r._messages)


def test_session_log_corrupt_tolerated():
    """损坏的 session 文件不阻断（load 容错——回放是优化不是生命线）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    p = _session_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{bad json", encoding="utf-8")
    from wuxing.session import SessionLog
    log = SessionLog(p)
    rows = log.load()
    assert rows == [], f"损坏文件应返回空：{rows}"


def test_session_log_append_only():
    """append-only：首次记录不被后续追加修改。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    p = _session_path(ws)
    from wuxing.session import SessionLog
    log = SessionLog(p)
    log.append(round_no=1, state="thinking", messages=[{"role": "user", "content": "m1"}])
    log.append(round_no=2, state="thinking", messages=[{"role": "user", "content": "m2"}])
    rows = log.load()
    assert rows[0]["messages"][0]["content"] == "m1", "首条不可被覆盖"
    assert len(rows) == 2


def test_session_file_includes_conversation_round():
    """真实测试暴露（2026-09-07）：session 文件必须含会话轮次——unit_id 每轮重用
    （F-0001…）→ 跨轮覆盖丢诊断数据。文件名 = {round}-{unit_id}.jsonl（无会话
    则保持 {unit_id}.jsonl——向后兼容）。"""
    import pathlib
    import tempfile

    from wuxing.config import EngineConfig
    from wuxing.conversation import ConversationState
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.loader import load_tools
    from wuxing.workspace import Workspace

    class _Llm:
        def __init__(self):
            self.usage_history = []
            self.call_count = 0

        def name(self):
            return "sp"

        def spec(self):
            return "sp"

        def supports_native_tools(self):
            return False

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.usage_history.append({"input": 0, "output": 0,
                                       "cache_read": 0, "cache_write": 0})
            return ToolCallResult(text="执行完成", tool_calls=[
                {"name": "write_artifact", "arguments": {
                    "path": "o.md", "kind": "result", "content": "x"}}])

    tmp = pathlib.Path(tempfile.mkdtemp())
    ws = Workspace(tmp)
    cfg = EngineConfig()
    st = ConversationState(tmp / "conv.jsonl")
    st.append_turn(1, "第一轮", [], "done")
    st.append_turn(2, "第二轮", [], "done")
    r = Runner(cfg, DomainRegistry(cfg), ws, _Llm(), load_tools(ws),
               conversation=st)
    r.run_unit("F-0001", "execute", {"goal": "g", "task": "t", "plan": "p",
                                    "result": "", "paths": ""})
    sess_dir = tmp / ".wuxing" / "sessions"
    files = [p.name for p in sess_dir.iterdir()]
    assert any("2-F-0001" in f for f in files), \
        f"session 文件名必须含会话轮次（防跨轮覆盖）：{files}"
