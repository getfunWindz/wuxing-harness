"""E3-2（P1）：生命周期事件——Subagent / Compact / UserPromptSubmit 注入点。"""
import pathlib

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


class _Llm:
    """最小 llm 桩（spec 非空——避开压缩链 mock 降级）。"""

    def spec(self):
        return "test-model"


def _mk_runner(tmp_path, **kw):
    keep = int(kw.pop("auto_compact_keep_recent_tokens", 50))
    cfg = EngineConfig(max_loop_rounds=1, max_unit_budget=1,
                       auto_compact_keep_recent_tokens=keep)
    ws = Workspace(pathlib.Path(tmp_path))
    return Runner(cfg, DomainRegistry(cfg), ws, _Llm(), BUILTIN_TOOLS(ws),
                  **kw)


def _conv_with_turns(tmp_path, n=3):
    from wuxing.conversation import ConversationState
    (pathlib.Path(tmp_path) / ".wuxing").mkdir(exist_ok=True)
    conv = ConversationState(pathlib.Path(tmp_path) / ".wuxing"
                             / "conversation.jsonl")
    for i in range(n):
        conv.append_turn(round_no=i + 1, user_text=f"第{i+1}轮 " + "x" * 300,
                         artifacts=[], summary="")
    return conv


# ---------------- Subagent 事件（delegate） ----------------

def test_delegate_emits_subagent_events():
    """E3-2/H3：delegate 起止事件（parent/goal/domain/status/artifacts）。"""
    from types import SimpleNamespace

    from wuxing.tools.delegate import DelegateTool

    def factory(goal, domain=None):
        class _Sub:
            _delegate_domain = domain or "plan"

            def run_unit(self, uid, dom, params):
                return SimpleNamespace(
                    status="ok", artifacts=[SimpleNamespace(path="a.md")],
                    logs=[], error="", unit_id=uid)
        return _Sub(), (lambda: None)

    events = []
    t = DelegateTool(factory, parent_unit_id="U-1")
    t._emit_event = events.append
    res = t.execute(goal="小小任务", domain="plan")
    assert res.status == "ok"
    assert [type(e).__name__ for e in events] == \
        ["SubagentStarted", "SubagentStopped"]
    assert events[0].parent_unit_id == "U-1"
    assert events[0].goal == "小小任务" and events[0].domain == "plan"
    assert events[1].status == "ok" and events[1].artifacts == 1


def test_delegate_zero_behavior_without_emitter():
    """E3-2/H3：未注入发射器 → 零行为（不崩）。"""
    from types import SimpleNamespace

    from wuxing.tools.delegate import DelegateTool

    def factory(goal, domain=None):
        class _Sub:
            _delegate_domain = "plan"

            def run_unit(self, uid, dom, params):
                return SimpleNamespace(status="ok", artifacts=[], logs=[],
                                       error="", unit_id=uid)
        return _Sub(), (lambda: None)

    t = DelegateTool(factory)
    assert t.execute(goal="g").status == "ok"


# ---------------- 压缩事件（Pre/PostCompact） ----------------

def test_compact_emits_pre_post_written(tmp_path, monkeypatch):
    """E3-2/H4：LLM 链压缩成功 → PreCompact + PostCompact(written)。"""
    r = _mk_runner(tmp_path)
    events = []
    r.emit_event = events.append
    r.conversation = _conv_with_turns(tmp_path)
    monkeypatch.setattr(r, "_llm_compaction_summary",
                        lambda turns, prev: "摘要" * 20)
    assert r._compact_llm_history("U-1", trigger=1, window=0) is True
    assert [type(e).__name__ for e in events] == ["PreCompact", "PostCompact"]
    assert events[0].to_round >= events[0].from_round >= 1
    assert events[0].source_tokens > 0
    assert events[1].status == "written" and events[1].summary_tokens > 0


def test_compact_emits_post_rejected(tmp_path, monkeypatch):
    """E3-2/H4：摘要不缩小被拒 → PostCompact(rejected)（事务纪律保留）。"""
    r = _mk_runner(tmp_path)
    events = []
    r.emit_event = events.append
    r.conversation = _conv_with_turns(tmp_path)
    monkeypatch.setattr(r, "_llm_compaction_summary",
                        lambda turns, prev: "长" * 4000)
    assert r._compact_llm_history("U-1", trigger=1, window=0) is False
    assert [type(e).__name__ for e in events] == ["PreCompact", "PostCompact"]
    assert events[1].status == "rejected"


def test_compact_degraded_emits_post(tmp_path, monkeypatch):
    """E3-2/H4：摘要调用异常 → PostCompact(degraded)（降级可见）。"""
    r = _mk_runner(tmp_path)
    events = []
    r.emit_event = events.append
    r.conversation = _conv_with_turns(tmp_path)

    def _boom(turns, prev):
        raise RuntimeError("provider down")

    monkeypatch.setattr(r, "_llm_compaction_summary", _boom)
    assert r._compact_llm_history("U-1", trigger=1, window=0) is False
    assert [type(e).__name__ for e in events] == ["PreCompact", "PostCompact"]
    assert events[1].status == "degraded"


def test_compact_no_conversation_zero_events(tmp_path):
    """E3-2/H4：无会话（不可达路径）→ 零事件（仅既有 degraded trace）。"""
    r = _mk_runner(tmp_path)
    events = []
    r.emit_event = events.append
    assert r._compact_llm_history("U-1", trigger=1, window=0) is False
    assert events == []


# ---------------- UserPromptSubmit（注入点） ----------------

def test_user_prompt_submit_collects_additional_context(tmp_path):
    """E3-2/H5：钩子 additional_context → 尾插用户消息（前缀不变）。"""
    r = _mk_runner(tmp_path)
    events = []
    r.emit_event = events.append
    r.hook_collect = lambda ev: [{"additional_context": "提示A"},
                                 {"unrelated": 1}]
    r._messages = []
    r._emit_user_prompt_submit("U-1", "execute", "任务提示")
    assert [type(e).__name__ for e in events] == ["UserPromptSubmit"]
    assert events[0].prompt == "任务提示" and events[0].unit_id == "U-1"
    assert r._messages == [{"role": "user",
                            "content": "[扩展上下文]\n提示A"}]


def test_user_prompt_submit_caps_and_traces(tmp_path):
    """E3-2/H5：注入上限 2000 字符 + trace extension_user_context。"""
    from wuxing.trace import TraceLogger
    r = _mk_runner(tmp_path, trace=TraceLogger(
        pathlib.Path(tmp_path) / ".wuxing" / "trace.jsonl"))
    r.hook_collect = lambda ev: [{"additional_context": "超" * 5000}]
    r._messages = []
    r._emit_user_prompt_submit("U-1", "plan", "p")
    content = r._messages[-1]["content"]
    assert content.startswith("[扩展上下文]\n") and len(content) <= 2000 + 8
    rows = (pathlib.Path(tmp_path) / ".wuxing" / "trace.jsonl").read_text(
        encoding="utf-8")
    assert "extension_user_context" in rows


def test_run_unit_triggers_user_prompt_submit(tmp_path):
    """E3-2/H5 接线：run_unit 装配完成后发射 UserPromptSubmit（收集面收到）。"""
    from wuxing.llm.mock import MockLlmProvider
    cfg = EngineConfig(max_loop_rounds=1, max_unit_budget=1,
                       use_real_shape=False)
    ws = Workspace(pathlib.Path(tmp_path))
    seen = []
    r = Runner(cfg, DomainRegistry(cfg), ws, MockLlmProvider(),
               BUILTIN_TOOLS(ws),
               hook_collect=lambda ev: (seen.append(ev), [])[1])
    r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert any(type(e).__name__ == "UserPromptSubmit" for e in seen)
