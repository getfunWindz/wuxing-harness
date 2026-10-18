"""TDD · S5-A/S5-B（A13 裁决 2026-10-06）：历史前置 + 折叠事件入 trace。

依据 `docs/WUXING_S5折叠复测_2026-10-04.md` §2-§3：
- S5-A：digest 每轮变化且位于 history 之前 → 跨轮命中止步 system；
  调整为 history 前置于 digest → append-only 历史段增量可命中。
- S5-B：折叠当前仅可从文本前缀「早期 N 轮已折叠」解析——机械事件化。
"""
import pathlib
import tempfile


class _SeenLlm:
    """捕获每次调用的装配消息（首调用=装配态——顺序/前缀断言用）。"""

    def __init__(self):
        self.seen = []

    def name(self):
        return "seen"

    def chat(self, messages, tools=None):
        self.seen.append([dict(m) for m in messages])
        from wuxing.llm.tool_results import ToolCallResult
        return ToolCallResult(text="完成", tool_calls=[
            {"name": "write_artifact",
             "arguments": {"path": "x.md", "kind": "result", "content": "v"}}])


def _mk(st, ws):
    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.loader import load_tools
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2, fsc_enabled=True)
    llm = _SeenLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws), conversation=st)
    return r, llm


def _ws():
    from wuxing.workspace import Workspace
    return Workspace(pathlib.Path(tempfile.mkdtemp()))


def test_history_precedes_digest_for_fresh_fragments():
    """S5-A：system 之后即历史段；摘要段在历史之后（不再占据最前缀位）。"""
    from wuxing.conversation import ConversationState
    st = ConversationState(pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl")
    st.append_turn(1, "上一轮任务", ["a.md"], summary="ok",
                   fragment_digest="[上一轮碎片上下文]\n- 摘要")
    r, llm = _mk(st, _ws())
    r.run_unit("U-1", "execute", {"goal": "g", "task": "t"})
    contents = [str(m.get("content", "")) for m in llm.seen[0]]
    assert contents[1].startswith("[会话历史]"), contents[:3]
    _hist = next(i for i, c in enumerate(contents)
                 if c.startswith("[会话历史]"))
    _dig = next(i for i, c in enumerate(contents)
                if c.startswith("[上一轮碎片上下文]"))
    assert _hist < _dig, contents[:4]


def test_cross_round_prefix_append_only():
    """S5-A 目标属性：下一轮装配字节流以上一轮 system+历史段为前缀。"""
    from wuxing.conversation import ConversationState
    ws = _ws()
    st = ConversationState(pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl")
    st.append_turn(1, "第一轮任务", ["a.md"], summary="ok",
                   fragment_digest="[上一轮碎片上下文]\n- 摘要1")
    r1, llm1 = _mk(st, ws)
    r1.run_unit("U-1", "execute", {"goal": "g", "task": "t"})
    st.append_turn(2, "第二轮任务", ["b.md"], summary="ok2",
                   fragment_digest="[上一轮碎片上下文]\n- 摘要2")
    r2, llm2 = _mk(st, ws)
    r2.run_unit("U-2", "execute", {"goal": "g", "task": "t"})
    a = "".join(str(m.get("content", "")) for m in llm1.seen[0][:2])  # system+历史
    b = "".join(str(m.get("content", "")) for m in llm2.seen[0])
    assert b.startswith(a), "跨轮前缀不连续（S5-A：历史段增量可命中）"


def test_history_folded_event_traced(tmp_path):
    """S5-B：折叠发生 → trace `history_folded`（folded/chars 机械化）。"""
    import json

    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    eng = Engine(cfg=EngineConfig(llm="mock", conversation_max_chars=150),
                 workdir=tmp_path, auto_confirm=True)
    sess = eng.start_session()
    for i in range(3):
        sess.send(f"任务{i}：" + "细节" * 60)
    rows = [json.loads(x) for x in
            (tmp_path / ".wuxing" / "trace.jsonl").read_text(
                encoding="utf-8").splitlines() if x.strip()]
    ev = [r for r in rows if r.get("event") == "history_folded"]
    assert ev, "缺少 history_folded trace 事件"
    assert all(int(r.get("folded") or 0) >= 1 for r in ev)
    assert all(r.get("chars") for r in ev)
