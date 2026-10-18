"""TDD：FSC 低匹配回退——「上一轮全部碎片上下文压缩 → 本轮复用缓存前置」。

用户裁决（2026-09-12）：FSC 默认开（用户可自主关闭）；FSC 覆盖不到的
（低匹配）碎片由跨轮碎片摘要兜底——前缀位注入（缓存友好）+ 确定性。
"""
import pathlib
import tempfile


def test_build_turn_digest_deterministic_and_bounded():
    """摘要构建：全部碎片、状态/产物/结果、确定性、字符上限。"""
    from wuxing.conversation import build_turn_digest
    from wuxing.protocols import UnitResult

    frags = [{"fragment_id": "F-1", "domain": "execute", "text": "实现教师信息页面"},
             {"fragment_id": "F-2", "domain": "verify", "text": "验收教师信息页面"}]
    u1 = UnitResult(unit_id="F-1", domain_id="execute", status="ok")
    u1.logs = ["执行成果：页面完成"]
    u1.deliverables = ["pages/teachers.vue"]
    u2 = UnitResult(unit_id="F-2", domain_id="verify", status="failed")
    d = build_turn_digest(frags, [u1, u2])
    assert d.startswith("[上一轮碎片上下文]")
    assert "实现教师信息页面" in d and "验收教师信息页面" in d
    assert "ok" in d and "failed" in d
    assert "pages/teachers.vue" in d
    assert build_turn_digest(frags, [u1, u2]) == d, "确定性（同输入同输出——缓存前提）"
    small = build_turn_digest(frags, [u1, u2], max_chars=60)
    assert len(small) <= 60, small
    assert build_turn_digest([], []) == ""


def test_conversation_state_prev_digest_roundtrip():
    """会话状态：摘要随轮次持久化；prev_digest 严格取「上一轮」。"""
    from wuxing.conversation import ConversationState
    st = ConversationState(pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl")
    assert st.prev_digest() == ""
    st.append_turn(1, "任务一", [], summary="ok", fragment_digest="[上一轮碎片上下文] A")
    assert st.prev_digest() == "[上一轮碎片上下文] A"
    st2 = ConversationState(st.path)
    assert st2.prev_digest() == "[上一轮碎片上下文] A", "持久化往返"
    st2.append_turn(2, "任务二", [], summary="ok")  # 无摘要轮
    assert st2.prev_digest() == "", "严格「上一轮」语义（空则空）"


def test_runner_injects_prev_digest_for_fresh_fragments():
    """低匹配回退：无 FSC 延续的碎片注入上一轮摘要（system 后/prompt 前）；
    FSC 关闭时不注入。"""
    from wuxing.config import EngineConfig
    from wuxing.conversation import ConversationState
    from wuxing.llm.tool_results import ToolCallResult
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.loader import load_tools
    from wuxing.workspace import Workspace

    class _SeenLlm:
        def __init__(self):
            self.seen = []

        def name(self):
            return "seen"

        def chat(self, messages, tools=None):
            self.seen.append([dict(m) for m in messages])
            return ToolCallResult(text="完成", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "x.md", "kind": "result", "content": "v"}}])

    st = ConversationState(pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl")
    st.append_turn(1, "上一轮任务", ["a.md"], summary="ok",
                   fragment_digest="[上一轮碎片上下文]\n- [execute] 实现页面 → ok")
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2, fsc_enabled=True)
    llm = _SeenLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws), conversation=st)
    r.run_unit("U-1", "execute", {"goal": "g", "task": "t"})
    contents = [str(m.get("content", "")) for m in llm.seen[0]]
    assert any("上一轮碎片上下文" in c for c in contents), contents
    # S5-A（A13 裁决 2026-10-06）：历史前置于摘要（append-only 前缀位）
    assert contents[1].startswith("[会话历史]"), contents[:3]
    _hist = next(i for i, c in enumerate(contents) if c.startswith("[会话历史]"))
    _dig = next(i for i, c in enumerate(contents)
                if c.startswith("[上一轮碎片上下文]"))
    assert _hist < _dig, contents[:4]
    # FSC 关闭 → 不注入
    cfg2 = EngineConfig(max_loop_rounds=2, max_unit_budget=2, fsc_enabled=False)
    llm2 = _SeenLlm()
    r2 = Runner(cfg2, DomainRegistry(cfg2), ws, llm2, load_tools(ws),
                conversation=st)
    r2.run_unit("U-2", "execute", {"goal": "g", "task": "t"})
    assert not any("上一轮碎片上下文" in str(m.get("content", ""))
                   for m in llm2.seen[0])


def test_session_send_records_fragment_digest():
    """会话 send：每轮记录碎片摘要（供下一轮低匹配回退——与 FSC 开关无关）。"""
    import json

    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    wd = pathlib.Path(tempfile.mkdtemp())
    eng = Engine(cfg=EngineConfig(fsc_enabled=False), workdir=wd,
                 auto_confirm=True)
    sess = eng.start_session()
    sess.send("做一个简单任务")
    rows = [json.loads(l) for l in (wd / ".wuxing" / "conversation.jsonl")
            .read_text(encoding="utf-8").splitlines() if l.strip()]
    assert rows and rows[-1].get("fragment_digest"), rows[-1]
