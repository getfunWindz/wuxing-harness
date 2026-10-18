"""TDD · L1-1：trace 采集器——评测原料（知识库「trace=评测原料」标准落地）。

trace 事件类型：unit_started / llm_call / tool_call / contract_check / unit_done。
Append-only JSONL（.wuxing/trace.jsonl）；行含 ts/event/unit_id/domain + 事件字段。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.engine import Engine
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.trace import TraceLogger
from wuxing.workspace import Workspace


class _ProbeLlm:
    """第一轮调 write_artifact（带参），第二轮收口。"""

    def __init__(self):
        self.calls = 0

    def name(self):
        return "probe"

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.calls += 1
        if self.calls == 1:
            return ToolCallResult(text="我先写产物", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "p.md", "kind": "plan", "content": "x"}}])
        return "方案：完整执行计划"


def _mk_runner(trace_dir):
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, _ProbeLlm(), load_tools(ws),
               trace=TraceLogger(trace_dir / "trace.jsonl"))
    return r, ws


def test_trace_file_created_with_key_events():
    """单单元跑完后：trace 文件存在且含关键事件类型（评测原料齐全）。"""
    td = pathlib.Path(tempfile.mkdtemp())
    r, _ = _mk_runner(td)
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok", res.error
    rows = TraceLogger(td / "trace.jsonl").load()
    events = {row["event"] for row in rows}
    assert rows, "trace 文件必须产生记录"
    assert {"unit_started", "llm_call", "tool_call", "contract_check",
            "unit_done"} <= events, f"缺失事件类型：{events}"


def test_trace_tool_call_has_status_and_latency():
    """tool_call 事件必须含：name / arg_hash / status / latency_ms（评测工具正确率原料）。"""
    td = pathlib.Path(tempfile.mkdtemp())
    r, _ = _mk_runner(td)
    r.run_unit("U-1", "plan", {"goal": "plan:x"})
    rows = TraceLogger(td / "trace.jsonl").load()
    tc = [x for x in rows if x["event"] == "tool_call"]
    assert tc, "缺 tool_call 事件"
    assert tc[0]["name"] == "write_artifact"
    assert len(tc[0]["arg_hash"]) == 8, "参数哈希（8 位指纹）"
    assert tc[0]["status"] in ("ok", "blocked", "error")
    assert tc[0]["latency_ms"] >= 0


def test_trace_events_ordered_per_unit():
    """按单元过滤：事件顺序 unit_started < llm_call < tool_call < unit_done（可回放）。"""
    td = pathlib.Path(tempfile.mkdtemp())
    r, _ = _mk_runner(td)
    r.run_unit("U-1", "plan", {"goal": "plan:x"})
    rows = [x for x in TraceLogger(td / "trace.jsonl").load()
            if x["unit_id"] == "U-1"]
    order = [x["event"] for x in rows]
    assert order.index("unit_started") < order.index("llm_call"), order
    assert order.index("tool_call") < order.index("unit_done"), order
    assert order[-1] == "unit_done", order
    # Contract check 与 done 均需在 LLM 调用之后
    assert order.index("contract_check") < order.index("unit_done"), order


def test_engine_assembles_trace():
    """引擎装配：run_task 自动产生 trace（shell/CLI 零配置）。"""
    wd = pathlib.Path(tempfile.mkdtemp())
    eng = Engine(workdir=wd, auto_confirm=True,
                 llm=_ProbeLlm())
    eng.run_task("写一份季度报告")
    tp = wd / ".wuxing" / "trace.jsonl"
    assert tp.exists(), "引擎运行必须自动写 trace（评测原料）"
    rows = TraceLogger(tp).load()
    assert any(x["event"] == "unit_done" for x in rows)


def test_trace_has_conversation_round():
    """Task7：真实测试埋点——会话轮次内 trace 行必须含 conversation_round。"""
    import pathlib
    import tempfile

    from wuxing.config import EngineConfig
    from wuxing.conversation import ConversationState
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.loader import load_tools
    from wuxing.trace import TraceLogger
    from wuxing.workspace import Workspace

    class _Llm:
        def __init__(self):
            self.usage_history = []
            self.call_count = 0

        def name(self):
            return "tr"

        def spec(self):
            return "tr"

        def supports_native_tools(self):
            return False

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.usage_history.append({"input": 1, "output": 1,
                                       "cache_read": 0, "cache_write": 0})
            return ToolCallResult(text="执行完成", tool_calls=[
                {"name": "write_artifact", "arguments": {
                    "path": "o.md", "kind": "result", "content": "x"}}])

    tmp = pathlib.Path(tempfile.mkdtemp())
    ws = Workspace(tmp)
    cfg = EngineConfig()
    st = ConversationState(tmp / "conv.jsonl")
    st.append_turn(1, "第一轮", [], "完成")
    tr = TraceLogger(tmp / "trace.jsonl")
    r = Runner(cfg, DomainRegistry(cfg), ws, _Llm(), load_tools(ws),
               trace=tr, conversation=st)
    r.run_unit("F-1", "execute", {"goal": "g", "task": "t", "plan": "p",
                                  "result": "", "paths": ""})
    rows = tr.load()
    assert rows, "trace 必须有事件"
    assert all(row.get("conversation_round") == 1 for row in rows), \
        f"所有 trace 行必须带会话轮次：{[row.get('conversation_round') for row in rows]}"


def test_trace_llm_reasoning_event():
    """思维链观测（2026-09-11 用户要求）：LLM 返回 reasoning（DeepSeek-flash
    reasoning_content）→ trace 落 llm_reasoning 事件（截断 3000）——
    用于分析模型在 harness 中的决策思维链。"""

    class ReasoningLlm(_ProbeLlm):
        def __init__(self):
            super().__init__()
            self._rc = "推理：先写产物再收口，预算有限"

        def _take_reasoning(self):
            r, self._rc = self._rc, ""
            return r

    td = pathlib.Path(tempfile.mkdtemp())
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, ReasoningLlm(), load_tools(ws),
               trace=TraceLogger(td / "trace.jsonl"))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok", res.error
    rows = TraceLogger(td / "trace.jsonl").load()
    rc = [x for x in rows if x.get("event") == "llm_reasoning"]
    assert rc, "必须落 llm_reasoning 事件（思维链可观测）"
    assert "先写产物" in rc[0].get("text", "")


def test_stream_unit_reasoning_event():
    """R4-3：思维链进事件流（壳渲染「思考块」）——emit_event 收到 unit_reasoning。"""

    class ReasoningLlm(_ProbeLlm):
        def __init__(self):
            super().__init__()
            self._rc = "流事件推理文本"

        def _take_reasoning(self):
            r, self._rc = self._rc, ""
            return r

    td = pathlib.Path(tempfile.mkdtemp())
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, ReasoningLlm(), load_tools(ws),
               trace=TraceLogger(td / "trace.jsonl"))
    events = []
    r.emit_event = events.append
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok", res.error
    rc = [e for e in events if type(e).__name__ == "UnitReasoning"]
    assert rc, "必须发 unit_reasoning 流事件（壳思维链渲染）"
    assert "流事件推理文本" in rc[0].text
    assert rc[0].unit_id == "U-1"


def test_tool_call_blocked_trace_reason():
    """BOX-M3：守卫阻断的 tool_call trace 带 reason 维度（命令审计可归因）。"""
    from wuxing.danger_guard import check_command

    class _DangerProbe:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "probe"

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.calls += 1
            if self.calls == 1:
                return ToolCallResult(text="试危险命令", tool_calls=[
                    {"name": "bash", "arguments": {"command": "rm -rf /"}}])
            return "收口"

    td = pathlib.Path(tempfile.mkdtemp())
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    trace = TraceLogger(td / "trace.jsonl")
    tools = load_tools(ws)
    tools.set_guard(lambda name, kwargs: (
        (check_command(kwargs.get("command", "")) or True)
        if name == "bash" else True))
    cfg = EngineConfig(max_loop_rounds=4, max_unit_budget=2)
    r = Runner(cfg, DomainRegistry(cfg), ws, _DangerProbe(), tools, trace=trace)
    r.run_unit("U-1", "execute", {"goal": "危险命令审计"})
    rows = [x for x in trace.load()
            if x.get("event") == "tool_call" and x.get("name") == "bash"
            and x.get("status") == "blocked"]
    assert rows, trace.load()
    assert "根/盘符/家目录删除" in str(rows[-1].get("reason", "")), rows[-1]


def test_stream_unit_reasoning_delta_events():
    """Task 2-2：chat_stream provider → unit_reasoning_delta 增量事件（实时渲染数据面）；
    收口仍发整段 unit_reasoning（兼容旧前端/观测），且增量合并 = 整段（不丢段）。"""

    class StreamProbeLlm(_ProbeLlm):
        def __init__(self):
            super().__init__()
            self._rc = "第一段" * 30 + "第二段"
            self.streamed = False

        def chat_stream(self, messages, tools=None, on_delta=None):
            if self.calls == 0:  # 首个调用（写产物轮）演示增量
                self.streamed = True
                for seg in ("第一段" * 30, "第二段"):
                    if on_delta:
                        on_delta("reasoning", seg)
            return self.chat(messages, tools)

        def _take_reasoning(self):
            r, self._rc = self._rc, ""
            return r

    td = pathlib.Path(tempfile.mkdtemp())
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = StreamProbeLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws),
               trace=TraceLogger(td / "trace.jsonl"))
    events = []
    r.emit_event = events.append
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok", res.error
    assert llm.streamed, "支持 chat_stream 的 provider 必须走流式路径（Task 1-3）"
    full = "第一段" * 30 + "第二段"
    deltas = [e for e in events if type(e).__name__ == "UnitReasoningDelta"]
    assert deltas, "必须发 unit_reasoning_delta 增量事件（壳增量渲染数据面）"
    assert all(d.unit_id == "U-1" and d.domain_id == "plan" for d in deltas)
    assert "".join(d.text for d in deltas) == full, "增量合并必须与整段一致（不丢段）"
    rc = [e for e in events if type(e).__name__ == "UnitReasoning"]
    assert rc and rc[0].text == full, "收口整段 unit_reasoning 保持兼容"


def test_stream_unit_reasoning_delta_capped():
    """Task 2-1：单条思考累计 10k 封顶——超限丢弃后续 delta + 仅落一条「已截断」提示。"""

    class FloodLlm(_ProbeLlm):
        def __init__(self):
            super().__init__()
            self.streamed = False

        def chat_stream(self, messages, tools=None, on_delta=None):
            if self.calls == 0:
                self.streamed = True
                for seg in ("x" * 6000, "y" * 6000, "z" * 6000):
                    if on_delta:
                        on_delta("reasoning", seg)
            return self.chat(messages, tools)

        def _take_reasoning(self):
            return ""

    td = pathlib.Path(tempfile.mkdtemp())
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = FloodLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws),
               trace=TraceLogger(td / "trace.jsonl"))
    events = []
    r.emit_event = events.append
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok", res.error
    assert llm.streamed
    deltas = [e for e in events if type(e).__name__ == "UnitReasoningDelta"]
    notices = [d for d in deltas if "已截断" in d.text]
    assert notices, "超限必须落「已截断」提示（不静默丢数据）"
    assert len(notices) == 1, "截断提示只落一条"
    body = "".join(d.text for d in deltas if "已截断" not in d.text)
    assert len(body) == 10000, "封顶后正文增量恰为 10k"
    assert "z" not in body, "超限后的 delta 必须丢弃"


def test_unit_reply_captured_from_final_assistant_text():
    """Task 4-1：单元收口 → UnitResult.reply = 最后一次助手文本。

    场景 A：工具轮带文本（真实主场景——模型边写产物边说总体回复）；
    场景 B：无工具轮的最终回复（verify 域——先读物证，文本轮收口）。
    """
    from wuxing.llm.tool_results import ToolCallResult

    class ToolTextLlm:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "tool-text"

        def chat(self, messages, tools=None):
            self.calls += 1
            return ToolCallResult(text="总体回复：方案已就绪", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "p.md", "kind": "plan",
                               "content": "x"}}])

    td = pathlib.Path(tempfile.mkdtemp())
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, ToolTextLlm(), load_tools(ws),
               trace=TraceLogger(td / "trace.jsonl"))
    res = r.run_unit("U-A", "plan", {"goal": "plan:x"})
    assert res.status == "ok", res.error
    assert res.reply == "总体回复：方案已就绪", \
        "工具轮携带的助手文本必须落 UnitResult.reply"

    class TextRoundLlm:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "text-round"

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return ToolCallResult(text="", tool_calls=[
                    {"name": "read_file", "arguments": {"path": "x.md"}}])
            return "结论：通过"

    root = pathlib.Path(tempfile.mkdtemp())
    (root / "x.md").write_text("hello", encoding="utf-8")
    r2 = Runner(cfg, DomainRegistry(cfg), Workspace(root), TextRoundLlm(),
                load_tools(ws), trace=TraceLogger(td / "trace2.jsonl"))
    res2 = r2.run_unit("U-B", "verify", {"paths": "x.md"})
    assert res2.status == "ok", res2.error
    assert res2.reply == "结论：通过", "无工具轮最终回复必须落 reply"


def test_unit_reply_empty_when_last_round_has_no_text():
    """Task 4-1：纯工具轮（无助手文本）→ reply 为空（不冒充总体回复）。"""

    class ToolOnlyLlm:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "tool-only"

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.calls += 1
            return ToolCallResult(text="", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": f"p{self.calls}.md", "kind": "plan",
                               "content": "x"}}])

    td = pathlib.Path(tempfile.mkdtemp())
    cfg = EngineConfig(max_loop_rounds=3, max_unit_budget=2)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, ToolOnlyLlm(), load_tools(ws),
               trace=TraceLogger(td / "trace.jsonl"))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok", res.error
    assert res.reply == ""


def test_tool_retrieval_traced_when_trimmed():
    """Task C2：工具检索裁剪生效时落 tool_retrieval trace（归因可观测）——
    决策可见（kept/dropped），选择结果本身不受观测影响（确定性保持）。"""
    td = pathlib.Path(tempfile.mkdtemp())
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4,
                       tool_retrieval_threshold=3, tool_retrieval_top_k=2)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, _ProbeLlm(), load_tools(ws),
               trace=TraceLogger(td / "trace.jsonl"))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok", res.error
    rows = TraceLogger(td / "trace.jsonl").load()
    tr = [row for row in rows if row["event"] == "tool_retrieval"]
    assert tr, "裁剪生效必须落 tool_retrieval trace（决策可观测）"
    row = tr[0]
    assert isinstance(row.get("kept"), list) and row["kept"], row
    assert isinstance(row.get("dropped"), list) and row["dropped"], row
    assert "load_skill" in row["kept"], "引擎级工具必须强制保留（forced）"
    assert "write_artifact" in row["kept"], \
        "契约物证工具必须强制保留（alwaysLoad——否则域契约必失败）"
