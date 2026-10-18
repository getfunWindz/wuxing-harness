"""E2-5（A10）：ask_user 挂起链（runner/engine）——fail-closed 与答复续跑。

纪律：无答复不自动选推荐项；同批独占；每单元 ≤3 次；答复经 resume 注入。
"""
import pathlib

from wuxing.config import EngineConfig
from wuxing.llm.tool_results import ToolCallResult
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.session import SessionLog
from wuxing.tools.ask_tool import AskUserTool
from wuxing.tools.base import ToolRegistry
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.trace import TraceLogger
from wuxing.workspace import Workspace


class ScriptedLlm:
    """按脚本输出 ToolCallResult；记录每次收到的消息（答复注入断言用）。"""

    def __init__(self, outs):
        self.outs = list(outs)
        self.received: list = []

    def name(self):
        return "scripted"

    def spec(self):
        return "mock"

    def chat(self, messages, tools=None):
        self.received.append(list(messages))
        if self.outs:
            return self.outs.pop(0)
        return ToolCallResult(text="完成声明：任务已完成", tool_calls=[])


def _runner(tmp_path, llm):
    cfg = EngineConfig(confirm_threshold=0.0, max_loop_rounds=3,
                       max_unit_budget=6)
    ws = Workspace(tmp_path)
    trace = TraceLogger(tmp_path / ".wuxing" / "trace.jsonl")
    tools = ToolRegistry(BUILTIN_TOOLS(ws) + [AskUserTool()])
    return Runner(cfg, DomainRegistry(cfg), ws, llm, tools, confirm_gate=None,
                  auto_confirm=True, trace=trace), trace


def _ask_call(title="选哪个格式？"):
    return {"name": "ask_user", "arguments": {"questions": [
        {"title": title, "options": ["Markdown", "纯文本"]}]}}


def _write_call(path="out.md"):
    return {"name": "write_artifact",
            "arguments": {"path": path, "content": "结果", "kind": "result"}}


def test_runner_pauses_on_ask(tmp_path):
    """首轮 ask_user → needs_answer（挂起）+ 审计对 + 会话存档可续。"""
    llm = ScriptedLlm([ToolCallResult(text="先确认格式", tool_calls=[_ask_call()])])
    r, trace = _runner(tmp_path, llm)
    res = r.run_unit("U-1", "execute", {"goal": "g", "plan": "p"})
    assert res.status == "needs_answer"
    pq = res.pending_question
    assert pq["question_id"] == "ask-U-1-1"
    assert pq["questions"][0]["title"] == "选哪个格式？"
    rows = [x for x in trace.load() if x.get("event") == "question_asked"]
    assert rows and rows[-1]["question_id"] == "ask-U-1-1"
    sess_dir = tmp_path / ".wuxing" / "sessions"
    files = sorted(sess_dir.glob("*-U-1.jsonl")) or sorted(sess_dir.glob("U-1.jsonl"))
    assert files, "会话存档必须存在（答复续跑配对用）"
    msgs = SessionLog(files[-1]).last_messages()
    assert any("[ask]" in str(m.get("content", "")) for m in msgs)
    assert any("先确认格式" in str(m.get("content", "")) for m in msgs)


def test_runner_resumes_with_answer(tmp_path):
    """答复（resume_session 尾附）→ 单元收敛 ok；答复必须进入续跑上下文。"""
    llm = ScriptedLlm([
        ToolCallResult(text="", tool_calls=[_write_call()]),
        ToolCallResult(text="完成声明：任务已完成", tool_calls=[]),
    ])
    r, _ = _runner(tmp_path, llm)
    history = [{"role": "system", "content": "sys"},
               {"role": "user", "content": "任务：g"},
               {"role": "user", "content": "[ask] ask-U-1-1 | 选哪个格式？"},
               {"role": "user", "content": "用户答复：Markdown"}]
    res = r.run_unit("U-1", "execute", {"goal": "g", "plan": "p"},
                     resume_session=history)
    assert res.status == "ok", res.error
    assert any("用户答复：Markdown" in str(m.get("content", ""))
               for m in llm.received[0]), "答复必须进入续跑上下文"


def test_ask_batch_exclusive_and_backfill(tmp_path):
    """同批：其余调用先回填；第二个 ask 返回错误结果；仅第一个入待答。"""
    llm = ScriptedLlm([
        ToolCallResult(text="先写再问", tool_calls=[
            _write_call("先写.md"),
            _ask_call(),
            _ask_call(title="第二问"),
        ]),
    ])
    r, _ = _runner(tmp_path, llm)
    res = r.run_unit("U-1", "execute", {"goal": "g", "plan": "p"})
    assert res.status == "needs_answer"
    logs = "\n".join(str(x) for x in res.logs)
    assert "write_artifact" in logs, "同批其余调用结果必须先回填"
    assert "同一批仅允许一个提问" in logs, "同批第二个 ask 必须返回错误结果"
    assert res.pending_question["questions"][0]["title"] == "选哪个格式？"


def test_ask_limit_per_unit(tmp_path):
    """每单元 ≤3 次：第 4 次 ask 被拦（错误结果，不挂起）。"""
    llm = ScriptedLlm([
        ToolCallResult(text="", tool_calls=[_ask_call()]),          # run1 ask-1
        ToolCallResult(text="", tool_calls=[_ask_call("第二问")]),   # run2 ask-2
        ToolCallResult(text="", tool_calls=[_ask_call("第三问")]),   # run3 ask-3
        ToolCallResult(text="", tool_calls=[_ask_call("第四问")]),   # run4 → 超限拦截
        ToolCallResult(text="", tool_calls=[_write_call()]),        # run4 继续
        ToolCallResult(text="完成声明：任务已完成", tool_calls=[]),   # run4 收敛
    ])
    r, _ = _runner(tmp_path, llm)
    history: list = []
    for _ in range(3):
        res = r.run_unit("U-1", "execute", {"goal": "g", "plan": "p"},
                         resume_session=history or None)
        assert res.status == "needs_answer", res.error
        history += [{"role": "user", "content": str(m)} for m in res.logs
                    if "[ask]" in str(m)]
        history.append({"role": "user", "content": "用户答复：Markdown"})
    # 第四次：超限拦截 → 模型转写物证并收尾
    res = r.run_unit("U-1", "execute", {"goal": "g", "plan": "p"},
                     resume_session=history)
    logs = "\n".join(str(x) for x in res.logs)
    assert "提问已达上限" in logs
    assert res.status == "ok", res.error


def test_engine_assembly_registers_ask_user(tmp_path):
    """引擎装配：ask_user 引擎级豁免 default_tools 粗筛（域白名单为闸）。"""
    from wuxing.engine import Engine
    eng = Engine(EngineConfig(llm="mock"), workdir=pathlib.Path(tmp_path))
    assert eng.tools.get("ask_user") is not None


# ---- T4：engine.answer_unit（fail-closed / 幂等 / 错配 / 续跑） ----


class _AnsLlm:
    """答复续跑脚本：写物证 → 完成声明。"""

    def __init__(self):
        self.received: list = []
        self.calls = 0

    def name(self):
        return "ans-scripted"

    def spec(self):
        return "mock"

    def chat(self, messages, tools=None):
        self.calls += 1
        self.received.append(list(messages))
        if self.calls == 1:
            return ToolCallResult(text="", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "out.md", "content": "结果",
                               "kind": "result"}}])
        return ToolCallResult(text="完成声明：任务已完成", tool_calls=[])


def _mk_answer_state(tmp_path, status="needs_answer", qid="ask-F-1-1"):
    """写入挂起任务状态 + 会话存档（answer 续跑材料）。"""
    from wuxing.protocols import UnitResult
    from wuxing.session import SessionLog
    from wuxing.state import TaskState, save_state
    wd = pathlib.Path(tmp_path)
    units = [UnitResult(
        unit_id="F-1", domain_id="execute", status=status,
        pending_question={"unit_id": "F-1", "domain_id": "execute",
                          "question_id": qid,
                          "questions": [{"title": "格式？",
                                         "options": ["md", "txt"],
                                         "multi": False}]})]
    frags = [{"fragment_id": "F-1", "domain": "execute", "deps": [],
              "text": "执行任务", "goal": "g",
              "granularity": None, "deliverables": []}]
    save_state(TaskState(task_text="提问任务", fragments=frags, units=units,
                         status="pending"), wd / "task_state.json")
    log = SessionLog(wd / ".wuxing" / "sessions" / "F-1.jsonl")
    log.append(round_no=0, state="seed", messages=[
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "任务：执行任务"}])
    log.append(round_no=1, state="needs_answer",
               messages=[{"role": "user",
                          "content": "[ask] ask-F-1-1 | 格式？"}],
               status="needs_answer")
    return wd


def _ans_engine(tmp_path, llm=None):
    from wuxing.engine import Engine
    return Engine(cfg=EngineConfig(max_loop_rounds=3, max_unit_budget=6,
                                   confirm_threshold=0.0),
                  workdir=pathlib.Path(tmp_path), llm=llm or _AnsLlm(),
                  auto_confirm=True)


def test_answer_fail_closed_no_auto_run(tmp_path):
    """无答复：resume 不重跑挂起单元（保持 pending）+ 事件补发可见。"""
    _mk_answer_state(tmp_path)
    llm = _AnsLlm()
    eng = _ans_engine(tmp_path, llm)
    events: list = []
    res = eng.resume_task(on_event=events.append)
    assert llm.calls == 0, "无答复不得自动重跑"
    assert res.status == "pending"
    assert any(type(e).__name__ == "UnitNeedsAnswer" for e in events)
    ans = [e for e in events if type(e).__name__ == "UnitNeedsAnswer"]
    assert ans and ans[0].kind == "", "模型提问 → kind 为空（壳按 AI 未核实标注）"


def test_answer_wrong_question_id_rejected(tmp_path):
    """question_id 错配 → 拒绝（不改状态不重跑）。"""
    import pytest
    _mk_answer_state(tmp_path)
    llm = _AnsLlm()
    eng = _ans_engine(tmp_path, llm)
    with pytest.raises(ValueError):
        eng.answer_unit("F-1", "ask-F-1-999", "md")
    assert llm.calls == 0
    from wuxing.state import load_state
    st = load_state(pathlib.Path(tmp_path) / "task_state.json")
    assert st.status == "pending"


def test_answer_resumes_and_converges(tmp_path):
    """答复续跑：注入答案 → 写物证收敛；审计对 question_answered 落 trace。"""
    _mk_answer_state(tmp_path)
    llm = _AnsLlm()
    eng = _ans_engine(tmp_path, llm)
    res = eng.answer_unit("F-1", "ask-F-1-1", "md", source="option")
    assert res.status == "done", res.report
    assert any("用户答复" in str(m.get("content", ""))
               for m in llm.received[0] if isinstance(m, dict))
    rows = [x for x in eng.trace.load()
            if x.get("event") == "question_answered"]
    assert rows and rows[-1]["question_id"] == "ask-F-1-1"


def test_answer_idempotent_first_wins(tmp_path):
    """重复答复：先到为准；第二次忽略 + trace（不改状态不重跑）。"""
    _mk_answer_state(tmp_path)
    llm = _AnsLlm()
    eng = _ans_engine(tmp_path, llm)
    first = eng.answer_unit("F-1", "ask-F-1-1", "md")
    calls_after_first = llm.calls
    second = eng.answer_unit("F-1", "ask-F-1-1", "txt")
    assert second.status == first.status == "done"
    assert llm.calls == calls_after_first, "二次答复不得重跑"
    ignored = [x for x in eng.trace.load()
               if x.get("event") == "question_answer_ignored"]
    assert ignored and ignored[-1]["question_id"] == "ask-F-1-1"
