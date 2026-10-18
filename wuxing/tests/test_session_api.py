"""TDD · 会话 API（Engine.start_session / ConversationSession.send）。"""
import pathlib
import tempfile
import typing

from wuxing.engine import Engine


class _SessionLlm:
    """按轮次产出不同内容——验证会话历史与交付物复用。"""

    def __init__(self):
        self.usage_history = []
        self.call_count = 0
        self.histories = []

    def name(self):
        return "sess"

    def spec(self):
        return "sess"

    def supports_native_tools(self):
        return False

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.usage_history.append({"input": 100, "output": 10,
                                   "cache_read": 50, "cache_write": 0})
        self.histories.append(list(messages))
        self.call_count += 1
        text = " ".join(m.get("content", "") for m in messages)
        if "总体回复" in text:
            # Task A2：生成总体回复调用（不再走单元分支）
            return "总结回复：任务已收口。"
        if "域：plan" in text:
            return ToolCallResult(text="方案：步骤", tool_calls=[
                {"name": "write_artifact", "arguments": {
                    "path": "plan.md", "kind": "plan", "content": "方案"}}])
        if "域：execute" in text:
            return ToolCallResult(text="执行完成", tool_calls=[
                {"name": "write_artifact", "arguments": {
                    "path": "out.md", "kind": "result", "content": "完成"}}])
        return "完成"


def test_two_turn_session_context_and_artifacts():
    """两轮会话：第2轮上下文含第1轮输入与交付物（会话段注入生效）。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    eng = Engine(workdir=tmp, llm=_SessionLlm(), auto_confirm=True)
    s = eng.start_session()
    r1 = s.send("实现一个函数")
    assert r1.status in ("done", "partial", "failed")
    n_hist_after_r1 = len(eng.llm.histories)
    r2 = s.send("再加一个参数")
    assert r2.status in ("done", "partial", "failed")
    # 第 2 轮的任一碎片上下文必须含第 1 轮信息（会话段）
    hist2 = eng.llm.histories[n_hist_after_r1:]
    joined = "\n".join(m.get("content", "") for h in hist2 for m in h)
    assert "[会话历史]" in joined, "第2轮必须注入会话历史段"
    assert "实现一个函数" in joined, "第1轮输入必须在会话段中"
    assert s.round_no == 2


def test_send_records_failed_round():
    """2026-10-01 真机 P1：run_task 抛异常（如 provider 构造失败）也必须留下轮次。

    现场：循迹模式续跑报『未配置 OPENAI_API_KEY』——失败提交在会话里毫无痕迹，
    用户回看时看不到自己发过什么、发生了什么（会话历史不可审阅）。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    eng = Engine(workdir=tmp, llm=_SessionLlm(), auto_confirm=True)
    s = eng.start_session()

    def _boom(*args, **kwargs):
        raise RuntimeError("未配置 OPENAI_API_KEY")

    eng.run_task = _boom   # 模拟引擎层异常（壳 manager 捕获前的原始传播）
    try:
        s.send("失败的任务")
        assert False, "异常必须继续向上抛出"
    except RuntimeError:
        # 期望 RuntimeError 继续上传（轮次计数断言在下方）
        pass
    assert s.round_no == 1, "失败轮次也必须计数入库"
    turns = s.state.turns
    assert turns and turns[-1].get("user_text") == "失败的任务"
    summary = str(turns[-1].get("summary", ""))
    assert "error" in summary.lower() or "失败" in summary
    assert "OPENAI_API_KEY" in summary


def test_session_persists_across_engine_instances():
    """会话持久化：同 workdir 新 Engine 实例恢复轮次历史（且历史段含旧轮次）。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    eng1 = Engine(workdir=tmp, llm=_SessionLlm(), auto_confirm=True)
    eng1.start_session().send("第一轮任务")
    eng2 = Engine(workdir=tmp, llm=_SessionLlm(), auto_confirm=True)
    s2 = eng2.start_session()
    assert s2.round_no == 1, "新实例必须恢复已持久化轮次"
    # 历史段必须含上一轮（缓存命中时可能不调 LLM——直接验证会话状态）
    assert "第一轮任务" in s2.state.context_text()
    s2.send("第二轮任务")
    assert s2.round_no == 2
    assert "第二轮任务" in s2.state.context_text()


def test_session_artifacts_cumulative():
    """交付物累计：会话 artifacts() 跨轮去重累计（每轮独立 workdir 可命中缓存）。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    eng = Engine(workdir=tmp, llm=_SessionLlm(), auto_confirm=True)
    s = eng.start_session()
    s.send("任务一")
    s.send("任务二")
    arts = s.artifacts()
    assert "plan.md" in arts and "out.md" in arts
    assert s.round_no == 2


def test_session_send_records_artifact_excerpts():
    """B2 集成：第 2 轮上下文必须含第 1 轮产物内容摘录（跨轮继承）。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    eng = Engine(workdir=tmp, llm=_SessionLlm(), auto_confirm=True)
    s = eng.start_session()
    s.send("实现一个函数")
    # 第 1 轮产物摘录已记录
    assert any(t.get("artifact_excerpts") for t in s.state.turns), \
        "轮次记录必须含产物摘录（B2）"
    s.send("继续")
    text = s.state.context_text()
    assert "产物摘录" in text or "exc" in str(s.state.turns), \
        "上下文段必须渲染产物摘录"


class _StubSessionEngine:
    """最小桩：只验证 send(unit=) 轮次标记（不走真引擎）。"""

    ws = None

    class cfg:
        fsc_digest_max_chars = 2000

    def run_task(self, user_text, on_event=None, conversation=None,
                 references=None, overrides=None):
        class _R:
            status = "done"
            units: typing.ClassVar[list] = []
            artifacts: typing.ClassVar[list] = []
            fragments: typing.ClassVar[list] = []
            metrics: typing.ClassVar[dict] = {}
        return _R()


def test_session_send_marks_unit_turn_and_isolates_context():
    """碎片会话后半程（2026-09-22）：send(unit=) 轮次带标记且不入主会话上下文。"""
    from wuxing.conversation import ConversationState
    from wuxing.session_api import ConversationSession

    p = pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl"
    sess = ConversationSession(_StubSessionEngine(), ConversationState(p))
    sess.send("普通任务")
    sess.send("碎片任务", unit="P-a")
    assert sess.state.turns[0].get("unit") is None
    assert sess.state.turns[1].get("unit") == "P-a"
    text = sess.state.context_text()
    assert "普通任务" in text and "碎片任务" not in text


def test_session_turn_records_reply_and_thoughts():
    """Task 4-2：会话行落 reply（模型总体回复）+ thoughts（可选，cap 30）。

    数据面：折叠卡片/历史轮摘要优先显示模型总体回复（无则回退机械 summary）。
    """

    class _ReplyLlm:
        def __init__(self):
            self.calls = 0
            self._rc = ""

        def name(self):
            return "reply"

        def spec(self):
            return "reply"

        def supports_native_tools(self):
            return False

        def _take_reasoning(self):
            r, self._rc = self._rc, ""
            return r

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.calls += 1
            self._rc = f"思考第{self.calls}步：先看仓库"
            if self.calls == 1:
                return ToolCallResult(text="我先写产物", tool_calls=[
                    {"name": "write_artifact", "arguments": {
                        "path": "plan.md", "kind": "plan", "content": "方案"}}])
            return "总体回复：方案已就绪"

    tmp = pathlib.Path(tempfile.mkdtemp())
    eng = Engine(workdir=tmp, llm=_ReplyLlm(), auto_confirm=True)
    s = eng.start_session()
    res = s.send("实现一个函数")
    assert res.status in ("done", "partial", "failed")
    row = s.state.turns[-1]
    assert "方案已就绪" in str(row.get("reply", "")), \
        "会话行必须落模型总体回复（reply）"
    thoughts = row.get("thoughts")
    assert isinstance(thoughts, list) and thoughts, "思维链须随行落盘（可选键）"
    assert any("思考第1步" in str(t.get("text", "")) for t in thoughts)
    assert all({"unit_id", "round", "text"} <= set(t) for t in thoughts)


def test_append_turn_omits_empty_optional_keys():
    """Task 4-2：空 reply/thoughts 不落键（旧行字节形状不变——前缀纪律）。"""
    from wuxing.conversation import ConversationState

    p = pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl"
    state = ConversationState(p)
    row = state.append_turn(1, "u", [], "summary")
    assert "reply" not in row and "thoughts" not in row
    row2 = state.append_turn(2, "u", [], "summary", reply="总体回复",
                             thoughts=[{"unit_id": "u1", "round": 1,
                                        "text": "思考"}])
    assert row2["reply"] == "总体回复"
    assert row2["thoughts"][0]["text"] == "思考"


def test_conversation_rewrite_turn_terminal():
    """v35 裁决（与专项同批）：会话行终态重写——pending 快照 → 终态补全。

    只改目标轮行的 summary/reply/thoughts/artifacts；user_text/ts/round 不变；
    未命中轮次 → None（无副作用）；持久化文件同步改写。
    """
    from wuxing.conversation import ConversationState

    p = pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl"
    state = ConversationState(p)
    state.append_turn(1, "任务A", [], "pending",
                      thoughts=[{"unit_id": "u0", "round": 1,
                                 "text": "确认前思考"}])
    state.append_turn(2, "任务B", [], "done；交付物 b.md")
    row = state.rewrite_turn(
        1, summary="done；交付物 a.md", reply="总体回复：A 已完成",
        thoughts=[{"unit_id": "u1", "round": 1, "text": "思考"}],
        artifacts=["a.md"])
    assert row is not None and row["reply"] == "总体回复：A 已完成"
    # 重载持久化确认（文件已改写而非内存幻觉）
    again = ConversationState(p)
    r1 = again.turns[0]
    assert r1["reply"] == "总体回复：A 已完成" and r1["artifacts"] == ["a.md"]
    # thoughts 合并（旧 + 新，不丢确认前思维链）
    assert [t["text"] for t in r1["thoughts"]] == ["确认前思考", "思考"]
    assert again.turns[1]["summary"].startswith("done；交付物 b.md")
    assert r1["user_text"] == "任务A" and "ts" in r1
    # 未命中轮次 → None（无副作用）
    assert state.rewrite_turn(9, summary="x") is None


def test_confirm_units_rewrites_conversation_turn():
    """确认续跑完成 → 本轮对话行重写为终态（不再永停 pending 快照）。"""
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    from wuxing.state import TaskState, save_state

    wd = pathlib.Path(tempfile.mkdtemp())
    save_state(TaskState(task_text="批量确认测试",
                         fragments=[{"fragment_id": "F-1", "domain": "execute",
                                     "deps": [], "text": "一"}],
                         units=[UnitResult(unit_id="F-1", domain_id="execute",
                                           status="needs_confirm")],
                         status="pending"),
               wd / "task_state.json")
    eng = Engine(cfg=EngineConfig(max_loop_rounds=2, max_unit_budget=2),
                 workdir=wd, llm=_SessionLlm(), auto_confirm=False)
    sess = eng.start_session()
    sess.state.append_turn(1, "批量确认测试", [], "pending")
    eng.confirm_units([("F-1", True)], reason="批准")
    row = sess.state.turns[-1]
    assert not str(row.get("summary", "")).startswith("pending"), \
        f"终态重写必须替换 pending 快照：{row}"
    assert "总结回复" in str(row.get("reply", "")), row


def test_confirm_rewrites_pending_row_even_with_existing_reply():
    """回归（真机 run 2/4）：pending 行已带 reply（部分单元先完成）→ 仍须终态重写。

    匹配锚点 = summary 的 pending 前缀（不是 reply 有无——reply 可能来自
    挂起前已完成的单元，不能当作未收口标记）。
    """
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    from wuxing.state import TaskState, save_state

    wd = pathlib.Path(tempfile.mkdtemp())
    frags = [{"fragment_id": "F-0", "domain": "execute", "deps": [], "text": "零"},
             {"fragment_id": "F-1", "domain": "execute", "deps": [], "text": "一"}]
    units = [UnitResult(unit_id="F-0", domain_id="execute", status="ok",
                        reply="先完成的回复"),
             UnitResult(unit_id="F-1", domain_id="execute",
                        status="needs_confirm")]
    save_state(TaskState(task_text="批量确认测试", fragments=frags,
                         units=units, status="pending"),
               wd / "task_state.json")
    eng = Engine(cfg=EngineConfig(max_loop_rounds=2, max_unit_budget=2),
                 workdir=wd, llm=_SessionLlm(), auto_confirm=False)
    sess = eng.start_session()
    sess.state.append_turn(1, "批量确认测试", [], "pending；交付物 a.md",
                           reply="先完成的回复")
    eng.confirm_units([("F-1", True)], reason="批准")
    row = sess.state.turns[-1]
    assert not str(row.get("summary", "")).startswith("pending"), \
        f"已带 reply 的 pending 行也必须终态重写：{row}"
    assert "总结回复" in str(row.get("reply", "")), row


def test_confirm_units_archives_internal_reports():
    """确认续跑路径也须归档契约报告（真机缺口：根目录残留 F-* 报告）。

    v35 裁决「报告=模型面」——首跑收口归档，但确认/续跑返回路径没走归档，
    续跑单元的 F-*.md 留在工作区根并被产物面板显示。
    """
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    from wuxing.state import TaskState, save_state

    wd = pathlib.Path(tempfile.mkdtemp())
    save_state(TaskState(task_text="批量确认测试",
                         fragments=[{"fragment_id": "F-1", "domain": "execute",
                                     "deps": [], "text": "一"}],
                         units=[UnitResult(unit_id="F-1", domain_id="execute",
                                           status="needs_confirm")],
                         status="pending"),
               wd / "task_state.json")
    eng = Engine(cfg=EngineConfig(max_loop_rounds=2, max_unit_budget=2),
                 workdir=wd, llm=_SessionLlm(), auto_confirm=False)
    eng.confirm_units([("F-1", True)], reason="批准")
    assert not list(wd.glob("F-1-*.md")), "契约报告不得留在工作区根"
    assert list((wd / ".wuxing" / "reports").glob("F-1-*.md")), \
        "契约报告必须归档到 .wuxing/reports/"


class _GenLlm:
    """Task A2 假 LLM：生成总体回复分支 + 先写产物的单元调用。"""

    def __init__(self):
        self.calls = 0

    def name(self):
        return "gen"

    def spec(self):
        return "gen"

    def supports_native_tools(self):
        return False

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        text = " ".join(m.get("content", "") for m in messages)
        self.calls += 1
        if "总体回复" in text:
            return "总结回复：已完成任务并交付产物。"
        if self.calls == 1:
            return ToolCallResult(text="我先写产物", tool_calls=[
                {"name": "write_artifact", "arguments": {
                    "path": "p.md", "kind": "plan", "content": "x"}}])
        return "单元收口文本"


def test_turn_reply_generated_by_engine():
    """Task A2：会话行 reply = 引擎生成的总体回复（pi 式），非单元最后文本。"""
    from wuxing.config import EngineConfig
    tmp = pathlib.Path(tempfile.mkdtemp())
    eng = Engine(workdir=tmp, llm=_GenLlm(), auto_confirm=True,
                 cfg=EngineConfig(max_loop_rounds=2, max_unit_budget=2))
    s = eng.start_session()
    r = s.send("实现一个函数")
    assert r.status in ("done", "partial", "failed")
    assert s.state.turns[-1].get("reply", "").startswith("总结回复"), \
        s.state.turns[-1]


def test_turn_reply_falls_back_when_disabled():
    """Task A2：关闭生成 → 回退最后非空单元 reply（不阻断）。"""
    from wuxing.config import EngineConfig
    tmp = pathlib.Path(tempfile.mkdtemp())
    eng = Engine(workdir=tmp, llm=_SessionLlm(), auto_confirm=True,
                 cfg=EngineConfig(max_loop_rounds=2, max_unit_budget=2,
                                  task_reply_enabled=False))
    s = eng.start_session()
    s.send("实现一个函数")
    row = s.state.turns[-1]
    assert row.get("reply") and "总结回复" not in row["reply"]
