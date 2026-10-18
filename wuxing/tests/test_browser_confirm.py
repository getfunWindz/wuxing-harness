"""TDD · O2-2 P1 T6：浏览器回环确认挂起接线（runner 泛化 + engine 决议钩子）。

设计：`docs/WUXING_内置浏览器体验断言_设计_2026-10-07.md` §3.2/§3.3。
纪律（交接 §8.1）：仅认「允许访问」选项标签；歧义/缺失/待决丢失 ⇒ fail-closed
拒绝（不得默认放行）。
"""
import pathlib

import pytest

from wuxing import browser_guard
from wuxing.config import EngineConfig
from wuxing.llm.tool_results import ToolCallResult
from wuxing.protocols import Tool, ToolResult
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.session import SessionLog
from wuxing.tools.ask_tool import AskUserTool
from wuxing.tools.base import ToolRegistry
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.trace import TraceLogger
from wuxing.workspace import Workspace


@pytest.fixture(autouse=True)
def _clean_pending():
    browser_guard.reset_pending_for_tests()
    yield
    browser_guard.reset_pending_for_tests()


class ScriptedLlm:
    """按脚本输出 ToolCallResult；记录每次收到的消息。"""

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


class ConfirmAskTool(Tool):
    """假 ask_user：直接携带 pending_questions/pending_meta 的挂起结果。"""

    def name(self):
        return "ask_user"

    def description(self):
        return "fake browser confirm"

    def input_schema(self):
        return {"type": "object", "properties": {}}

    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": False, "destructive": False}

    def execute(self, **kw):
        return ToolResult(
            status="needs_answer", tool_name=self.name(),
            content="[browser] 回环访问待确认：127.0.0.1:8899",
            pending_questions=[{
                "title": "内置浏览器要访问本机地址 127.0.0.1:8899。"
                         "是否允许本次访问？",
                "options": ["允许访问", "拒绝"]}],
            pending_meta={"kind": "browser_access", "pending_id": "pend-1",
                          "address": "127.0.0.1:8899"})


def _runner(tmp_path, llm, extra=None):
    cfg = EngineConfig(confirm_threshold=0.0, max_loop_rounds=3,
                       max_unit_budget=6)
    ws = Workspace(tmp_path)
    trace = TraceLogger(tmp_path / ".wuxing" / "trace.jsonl")
    tools = ToolRegistry(BUILTIN_TOOLS(ws) + list(extra or []))
    return Runner(cfg, DomainRegistry(cfg), ws, llm, tools, confirm_gate=None,
                  auto_confirm=True, trace=trace), trace


# ---- ① ToolResult 契约（T4 已落地——防回退） ----


def test_toolresult_pending_fields_default():
    tr = ToolResult()
    assert tr.pending_questions == []
    assert tr.pending_meta == {}


# ---- ② runner 泛化：工具自带 pending_questions/pending_meta ----


def test_runner_generic_pending_suspend(tmp_path):
    """工具返回 needs_answer 且带 pending_* → 挂起 + kind/meta 入档 + trace。"""
    llm = ScriptedLlm([ToolCallResult(text="需确认", tool_calls=[
        {"name": "ask_user", "arguments": {}}])])
    r, trace = _runner(tmp_path, llm, extra=[ConfirmAskTool()])
    res = r.run_unit("U-1", "execute", {"goal": "g", "plan": "p"})
    assert res.status == "needs_answer"
    pq = res.pending_question
    assert pq["kind"] == "browser_access"
    assert pq["meta"]["pending_id"] == "pend-1"
    assert pq["meta"]["address"] == "127.0.0.1:8899"
    assert pq["questions"][0]["options"] == ["允许访问", "拒绝"]
    rows = [x for x in trace.load() if x.get("event") == "question_asked"]
    assert rows and rows[-1]["kind"] == "browser_access"
    assert rows[-1].get("surface") == "question"
    assert rows[-1].get("source") == "mechanism"


def test_runner_ask_fallback_kind_empty(tmp_path):
    """无 pending_questions → 回退 ask_user.last_questions（既有行为不回归）。"""
    llm = ScriptedLlm([ToolCallResult(text="先问", tool_calls=[
        {"name": "ask_user",
         "arguments": {"questions": [{"title": "选哪个格式？",
                                      "options": ["Markdown", "纯文本"]}]}}])])
    r, trace = _runner(tmp_path, llm, extra=[AskUserTool()])
    res = r.run_unit("U-1", "execute", {"goal": "g", "plan": "p"})
    assert res.status == "needs_answer"
    assert res.pending_question["kind"] == ""
    assert res.pending_question["meta"] == {}
    assert res.pending_question["questions"][0]["title"] == "选哪个格式？"
    rows = [x for x in trace.load() if x.get("event") == "question_asked"]
    assert rows and rows[-1].get("source") == "model"


# ---- ③ 答复标签解析：保守（fail-closed） ----


def test_parse_access_decision_fail_closed():
    assert browser_guard.parse_access_decision("Q1 是否允许？：允许访问") is True
    assert browser_guard.parse_access_decision("Q1 是否允许？：拒绝") is False
    assert browser_guard.parse_access_decision("随便") is False
    assert browser_guard.parse_access_decision("") is False
    # 注入抵抗：题面含「允许访问」字样 + 自由文本 → 不得默认放行
    assert browser_guard.parse_access_decision(
        "Q1 题面带允许访问字样：我不知道") is False
    # 否定自由文本（尾段非精确标签）→ fail-closed
    assert browser_guard.parse_access_decision("Q1 x：不允许访问") is False


# ---- ④ engine 决议钩子（kind=browser_access） ----


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


def _mk_browser_state(tmp_path, pending_id="pend-1",
                      address="127.0.0.1:8899"):
    """写入浏览器确认挂起状态 + 会话存档（answer 续跑材料）。"""
    from wuxing.protocols import UnitResult
    from wuxing.state import TaskState, save_state
    wd = pathlib.Path(tmp_path)
    pq = {"unit_id": "F-1", "domain_id": "execute",
          "question_id": "ask-F-1-1",
          "questions": [{
              "title": "内置浏览器要访问本机地址 127.0.0.1:8899。",
              "options": ["允许访问", "拒绝"], "multi": False}],
          "kind": "browser_access",
          "meta": {"kind": "browser_access", "pending_id": pending_id,
                   "address": address}}
    units = [UnitResult(unit_id="F-1", domain_id="execute",
                        status="needs_answer", pending_question=pq)]
    frags = [{"fragment_id": "F-1", "domain": "execute", "deps": [],
              "text": "访问本地页面", "goal": "g",
              "granularity": None, "deliverables": []}]
    save_state(TaskState(task_text="浏览器确认任务", fragments=frags,
                         units=units, status="pending"),
               wd / "task_state.json")
    log = SessionLog(wd / ".wuxing" / "sessions" / "F-1.jsonl")
    log.append(round_no=0, state="seed", messages=[
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "任务：访问本地页面"}])
    log.append(round_no=1, state="needs_answer",
               messages=[{"role": "user",
                          "content": "[ask] ask-F-1-1 | 回环待确认"}],
               status="needs_answer")
    return wd


def _ans_engine(tmp_path, llm=None):
    from wuxing.engine import Engine
    return Engine(cfg=EngineConfig(max_loop_rounds=3, max_unit_budget=6,
                                   confirm_threshold=0.0),
                  workdir=pathlib.Path(tmp_path), llm=llm or _AnsLlm(),
                  auto_confirm=True)


def _register_pending():
    """注册真实待决（已识别占用者）→ 返回 (pending_id, address)。"""
    occ = browser_guard.Occupant(pid=42, exe="python.exe",
                                 cmdline="python -m http.server 8899",
                                 label="python")
    d = browser_guard.check_loopback("127.0.0.1", 8899,
                                     probe=lambda h, p: True,
                                     identify=lambda p: occ)
    assert d.kind == "confirm_required"
    return d.pending_id, d.address


def _patch_store(tmp_path, monkeypatch):
    store = pathlib.Path(tmp_path) / "allow.json"
    monkeypatch.setattr(browser_guard, "default_store_path", lambda: store)
    return store


def test_engine_browser_allow_resolves_and_resumes(tmp_path, monkeypatch):
    """「允许访问」→ 护栏条目落盘 + browser_access_decided 审计 + 续跑。"""
    store = _patch_store(tmp_path, monkeypatch)
    pid, address = _register_pending()
    _mk_browser_state(tmp_path, pending_id=pid, address=address)
    llm = _AnsLlm()
    eng = _ans_engine(tmp_path, llm)
    res = eng.answer_unit("F-1", "ask-F-1-1",
                          "Q1 是否允许本次访问？：允许访问", source="option")
    assert res.status == "done", res.report
    data = browser_guard.load_allow(store_path=store)
    assert len(data["entries"]) == 1
    assert data["entries"][0]["address"] == address
    assert any("用户答复" in str(m.get("content", ""))
               for m in llm.received[0] if isinstance(m, dict))
    decided = [x for x in eng.trace.load()
               if x.get("event") == "browser_access_decided"]
    assert decided and decided[-1]["approved"] is True


def test_engine_browser_deny_no_entry(tmp_path, monkeypatch):
    """「拒绝」→ 不写条目 + 审计 approved=False。"""
    store = _patch_store(tmp_path, monkeypatch)
    pid, address = _register_pending()
    _mk_browser_state(tmp_path, pending_id=pid, address=address)
    eng = _ans_engine(tmp_path)
    res = eng.answer_unit("F-1", "ask-F-1-1", "Q1 是否允许？：拒绝",
                          source="option")
    assert res.status == "done", res.report
    assert browser_guard.load_allow(store_path=store)["entries"] == []
    decided = [x for x in eng.trace.load()
               if x.get("event") == "browser_access_decided"]
    assert decided and decided[-1]["approved"] is False


def test_engine_browser_ambiguous_fail_closed(tmp_path, monkeypatch):
    """自由文本/歧义 → fail-closed 拒绝（不写条目）。"""
    store = _patch_store(tmp_path, monkeypatch)
    pid, address = _register_pending()
    _mk_browser_state(tmp_path, pending_id=pid, address=address)
    eng = _ans_engine(tmp_path)
    res = eng.answer_unit("F-1", "ask-F-1-1", "我不确定，随便吧")
    assert res.status == "done", res.report
    assert browser_guard.load_allow(store_path=store)["entries"] == []
    decided = [x for x in eng.trace.load()
               if x.get("event") == "browser_access_decided"]
    assert decided and decided[-1]["approved"] is False


def test_engine_browser_unknown_pending_fail_closed(tmp_path, monkeypatch):
    """待决丢失（如进程重启）→ 不写条目 + 留痕（绝不默认放行）。"""
    store = _patch_store(tmp_path, monkeypatch)
    _mk_browser_state(tmp_path, pending_id="gone-1")
    eng = _ans_engine(tmp_path)
    res = eng.answer_unit("F-1", "ask-F-1-1", "Q1 是否允许？：允许访问")
    assert res.status == "done", res.report
    assert not store.exists() or (
        browser_guard.load_allow(store_path=store)["entries"] == [])
    decided = [x for x in eng.trace.load()
               if x.get("event") == "browser_access_decided"]
    assert decided and decided[-1]["approved"] is False


def test_engine_browser_wrong_qid_no_resolve(tmp_path, monkeypatch):
    """question_id 错配 → ValueError；不决议、不重跑（既有语义）。"""
    store = _patch_store(tmp_path, monkeypatch)
    pid, address = _register_pending()
    _mk_browser_state(tmp_path, pending_id=pid, address=address)
    llm = _AnsLlm()
    eng = _ans_engine(tmp_path, llm)
    with pytest.raises(ValueError):
        eng.answer_unit("F-1", "ask-F-1-999", "Q1 是否允许？：允许访问")
    assert llm.calls == 0
    assert not store.exists()


def test_pending_kind_meta_roundtrip(tmp_path):
    """挂起态持久化回读：kind/meta 字段不丢（asdict 往返）。"""
    from wuxing.protocols import UnitResult
    from wuxing.state import TaskState, load_state, save_state
    pq = {"unit_id": "F-1", "domain_id": "execute",
          "question_id": "ask-F-1-1", "questions": [],
          "kind": "browser_access",
          "meta": {"kind": "browser_access", "pending_id": "p-9",
                   "address": "127.0.0.1:1"}}
    state = TaskState(task_text="t", fragments=[], units=[UnitResult(
        unit_id="F-1", domain_id="execute", status="needs_answer",
        pending_question=pq)], status="pending")
    save_state(state, pathlib.Path(tmp_path) / "task_state.json")
    loaded = load_state(pathlib.Path(tmp_path) / "task_state.json")
    got = loaded.units[0].pending_question
    assert got["kind"] == "browser_access"
    assert got["meta"]["pending_id"] == "p-9"
    assert got["meta"]["address"] == "127.0.0.1:1"


def test_resume_reemit_carries_question_kind(tmp_path):
    """恢复态提问补发必须带 kind（壳据此选「机制生成」标注）。"""
    _mk_browser_state(tmp_path)
    eng = _ans_engine(tmp_path)
    events: list = []
    eng.resume_task(on_event=events.append)
    ans = [e for e in events if type(e).__name__ == "UnitNeedsAnswer"]
    assert ans and ans[0].kind == "browser_access"
