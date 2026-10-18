"""G7：自动压缩（预算/触发/压缩行/LLM 链）（设计 §7）。"""


def test_autocompact_config_defaults_and_schema():
    """4 键双写：默认值/类型/一致性 + 负值早报。"""
    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS, validate_config
    cfg = EngineConfig()
    assert cfg.auto_trim_enabled is True
    assert cfg.auto_trim_reserve_tokens == 16384
    assert cfg.auto_compact_llm_enabled is False
    assert cfg.auto_compact_keep_recent_tokens == 20000
    spec = {s.name: s for s in FIELD_SPECS}
    assert spec["auto_trim_enabled"].default is True
    assert spec["auto_trim_reserve_tokens"].default == 16384
    assert spec["auto_compact_llm_enabled"].default is False
    assert spec["auto_compact_keep_recent_tokens"].default == 20000
    assert spec["auto_trim_enabled"].type == "bool"
    assert spec["auto_trim_reserve_tokens"].type == "int"
    assert validate_config({"auto_trim_reserve_tokens": -1})
    assert validate_config({"auto_compact_keep_recent_tokens": -1})
    assert validate_config({"auto_trim_reserve_tokens": 0}) == []


# ---- Task 2：自动预算（触发/滞回/零行为）----

def _cfg(reserve=50, enabled=True):
    from wuxing.config import EngineConfig
    # E2-2（G7 v2）：新余量键显式归零/置 1.0，保持既有测试的原触发语义
    return EngineConfig(auto_trim_enabled=enabled,
                        auto_trim_reserve_tokens=reserve,
                        auto_trim_output_reserve_tokens=0,
                        auto_trim_trigger_ratio=1.0)


def _hist_msgs(pad=400):
    return [{"role": "system", "content": "S"},
            {"role": "user", "content": "[会话历史]\n" + "旧" * pad},
            {"role": "user", "content": "任务提示"}]


def test_effective_budget_states():
    from wuxing.context_budget import effective_budget
    assert effective_budget(_cfg(), 300, 100) == 100      # 会话预算优先
    assert effective_budget(_cfg(), 300) == 250           # 自动触发线
    assert effective_budget(_cfg(enabled=False), 300) == 0
    assert effective_budget(_cfg(), 0) == 0               # 非法窗口
    assert effective_budget(_cfg(), 50) == 0              # REAL-18：窗口 ≤ reserve → 禁用


def test_trim_target_hysteresis_and_clamp():
    from wuxing.context_budget import trim_target
    assert trim_target(_cfg(), 300, 250) == 200           # max(150, 300-100)
    assert trim_target(_cfg(), 100, 50) == 50             # 小窗口：不得高于触发线
    assert trim_target(_cfg(), 0, 10) == 10


def test_apply_auto_trim_trigger_and_hysteresis():
    from wuxing.context_budget import apply_auto_trim
    out, trimmed, used, auto = apply_auto_trim(_hist_msgs(), _cfg(), 300, len)
    assert auto is True and used == 200
    assert sum(len(str(m["content"])) for m in out) <= 200
    assert any(t["key"] == "history" for t in trimmed)


def test_apply_auto_trim_zero_behavior():
    from wuxing.context_budget import apply_auto_trim
    msgs = _hist_msgs(pad=2)
    out, trimmed, used, auto = apply_auto_trim(msgs, _cfg(), 300, len)
    assert out == msgs and trimmed == [] and used == 0 and auto is False
    out2, _, _, _ = apply_auto_trim(msgs, _cfg(enabled=False), 300, len)
    assert out2 == msgs


def test_apply_auto_trim_session_budget_unchanged():
    from wuxing.context_budget import apply_auto_trim
    out, trimmed, used, auto = apply_auto_trim(_hist_msgs(), _cfg(), 300, len,
                                               session_budget=120)
    assert auto is False and used == 120 and trimmed
    assert sum(len(str(m["content"])) for m in out) <= 120


# ---- Task 3：压缩行（渲染/跳过/迭代/兼容）----

def _write_rows(path, rows):
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                    + "\n", encoding="utf-8")


def _turn(rnd, text, digest=""):
    row = {"round": rnd, "user_text": text, "artifacts": [], "summary": "done",
           "ts": 1000.0 + rnd}
    if digest:
        row["fragment_digest"] = digest
    return row


def _comp(from_round, to_round, summary="COMPACT-SUMMARY-XYZ"):
    return {"type": "compaction", "from_round": from_round,
            "to_round": to_round, "summary": summary, "mode": "llm",
            "ts": 2000.0}


def test_compaction_row_renders_and_skips(tmp_path):
    from wuxing.conversation import ConversationState
    p = tmp_path / "conversation-a.jsonl"
    _write_rows(p, [_turn(1, "第一轮"), _turn(2, "第二轮"), _comp(1, 2),
                    _turn(3, "第三轮")])
    st = ConversationState(p)
    text = st.context_text(max_chars=10000)
    assert "第一轮" not in text and "第二轮" not in text
    assert "[历史压缩]" in text and "COMPACT-SUMMARY-XYZ" in text
    assert "第三轮" in text
    assert text.index("[历史压缩]") < text.index("第3轮")
    assert st.round_no == 3


def test_compaction_turn_views_mark_compacted(tmp_path):
    from wuxing.conversation import ConversationState
    p = tmp_path / "conversation-a.jsonl"
    _write_rows(p, [_turn(1, "第一轮"), _turn(2, "第二轮"), _comp(1, 1),
                    _turn(3, "第三轮")])
    st = ConversationState(p)
    views = st.turn_views()
    assert [(v["round"], v["compacted"]) for v in views] == [
        (1, True), (2, False), (3, False)]
    assert "COMPACT-SUMMARY-XYZ" not in str(views[0].get("user_text", ""))


def test_compaction_prev_digest_skips_covered(tmp_path):
    from wuxing.conversation import ConversationState
    p = tmp_path / "conversation-a.jsonl"
    _write_rows(p, [_turn(1, "第一轮", "dig1"), _turn(2, "第二轮", "dig2"),
                    _comp(1, 2), _turn(3, "第三轮", "dig3")])
    assert ConversationState(p).prev_digest() == "dig3"
    p2 = tmp_path / "conversation-b.jsonl"
    _write_rows(p2, [_turn(1, "第一轮", "dig1"), _turn(2, "第二轮", "dig2"),
                     _comp(1, 2)])
    assert ConversationState(p2).prev_digest() == ""  # 覆盖轮不回流


def test_compaction_multiple_uses_latest(tmp_path):
    from wuxing.conversation import ConversationState
    p = tmp_path / "conversation-a.jsonl"
    _write_rows(p, [_turn(1, "第一轮"), _turn(2, "第二轮"),
                    _comp(1, 2, "摘要A"), _turn(3, "第三轮"), _turn(4, "第四轮"),
                    _comp(1, 4, "摘要B"), _turn(5, "第五轮")])
    text = ConversationState(p).context_text(max_chars=10000)
    assert "摘要B" in text and "摘要A" not in text
    assert all(f"第{n}轮" not in text for n in (1, 2, 3, 4))
    assert "第五轮" in text


def test_append_row_roundtrip(tmp_path):
    from wuxing.conversation import ConversationState
    p = tmp_path / "conversation-a.jsonl"
    st = ConversationState(p)
    st.append_turn(1, "第一轮", [])
    st.append_row(_comp(1, 1))
    st2 = ConversationState(p)
    assert st2.round_no == 1
    assert any(str(t.get("type")) == "compaction" for t in st2.turns)


def test_handoff_skips_compaction_rows(tmp_path):
    from wuxing.handoff import build_brief
    conv = tmp_path / ".wuxing" / "conversation-a.jsonl"
    _write_rows(conv, [_turn(1, "第一轮"), _comp(1, 1), _turn(2, "第二轮")])
    brief = build_brief(tmp_path, conv)
    assert "COMPACT-SUMMARY-XYZ" not in brief["brief"]


# ---- Task 4：LLM 摘要链（runner 触发/降级/迭代）----

class _FakeCompLlm:
    def __init__(self, text="LLM-COMPACT-摘要"):
        self.text = text
        self.calls = []

    def spec(self): return "deepseek:fake-compact"
    def name(self): return "fake-compact"
    def supports_native_tools(self): return True

    def chat(self, messages, tools=None):
        self.calls.append(messages)
        return self.text


def _compact_runner(tmp_path, llm=None, keep_recent=5, enabled=True):
    from wuxing.config import EngineConfig
    from wuxing.runner import Runner
    from wuxing.trace import TraceLogger
    from wuxing.workspace import Workspace
    ws = Workspace(tmp_path)
    trace = TraceLogger(tmp_path / ".wuxing" / "trace.jsonl")
    cfg = EngineConfig(auto_compact_llm_enabled=enabled,
                       auto_compact_keep_recent_tokens=keep_recent)
    conv = tmp_path / ".wuxing" / "conversation-a.jsonl"
    _write_rows(conv, [_turn(1, "第一轮需求" + "x" * 30, "done1"),
                       _turn(2, "第二轮需求" + "x" * 30, "done2"),
                       _turn(3, "第三轮需求", "done3")])
    from wuxing.conversation import ConversationState
    state = ConversationState(conv)
    runner = Runner(cfg, None, ws, llm, [], trace=trace, conversation=state)
    runner._current_domain_id = "execute"
    return runner, state, trace


def test_compact_llm_writes_row_and_traces(tmp_path):
    fake = _FakeCompLlm()
    runner, state, trace = _compact_runner(tmp_path, llm=fake)
    assert runner._compact_llm_history("F-0001", trigger=10) is True
    comp = state.last_compaction()
    assert comp is not None and comp["summary"] == "LLM-COMPACT-摘要"
    assert comp["from_round"] == 1 and comp["to_round"] >= 2
    assert fake.calls  # 真实调用了模型
    assert any(r["event"] == "compaction_written" for r in trace.load())
    text = state.context_text(max_chars=10000)
    assert "[历史压缩]" in text and "LLM-COMPACT-摘要" in text


def test_compact_llm_no_conversation_traced(tmp_path):
    """B3（E0-3）：headless（无 conversation）压缩不可达须落 trace reason。"""
    from wuxing.config import EngineConfig
    from wuxing.runner import Runner
    from wuxing.trace import TraceLogger
    from wuxing.workspace import Workspace
    ws = Workspace(tmp_path)
    trace = TraceLogger(tmp_path / ".wuxing" / "trace.jsonl")
    runner = Runner(EngineConfig(), None, ws, object(), [], trace=trace)
    runner._current_domain_id = "execute"
    assert runner._compact_llm_history("F-0001", trigger=10) is False
    rows = [r for r in trace.load()
            if r.get("event") == "compaction_degraded"]
    assert rows and rows[-1].get("reason") == "no_conversation", rows


def test_compact_llm_degrades_when_mock(tmp_path):
    # 默认 Engine 的 MockLlmProvider 等价物：无 spec 的假 llm
    class _MockLike:
        def spec(self): return "mock"
        def name(self): return "mock"
        def chat(self, messages, tools=None): return "不该被调用"
    runner, state, trace = _compact_runner(tmp_path, llm=_MockLike())
    assert runner._compact_llm_history("F-0001", trigger=10) is False
    assert state.last_compaction() is None
    assert any(r["event"] == "compaction_degraded" for r in trace.load())


def test_compact_llm_no_span_when_all_recent(tmp_path):
    fake = _FakeCompLlm()
    runner, state, _trace = _compact_runner(tmp_path, llm=fake,
                                             keep_recent=100000)
    assert runner._compact_llm_history("F-0001", trigger=10) is False
    assert state.last_compaction() is None
    assert not fake.calls


def test_compact_llm_iterates_from_previous_start(tmp_path):
    fake = _FakeCompLlm()
    runner, state, _trace = _compact_runner(tmp_path, llm=fake)
    assert runner._compact_llm_history("F-0001", trigger=10) is True
    first = state.last_compaction()
    assert first["from_round"] == 1
    # 再加两轮 → 二次压缩：from 沿用旧起点，且携带旧摘要（迭代）
    state.append_turn(state.round_no + 1, "第四轮需求", [])
    state.append_turn(state.round_no + 1, "第五轮需求", [])
    assert runner._compact_llm_history("F-0001", trigger=10) is True
    second = state.last_compaction()
    assert second["from_round"] == 1
    assert second["to_round"] > first["to_round"]
    import json as _json
    assert "LLM-COMPACT-摘要" in _json.dumps(fake.calls[-1], ensure_ascii=False)


# ---- Task 5：可见性（preview compacted + 自动预算）----

def test_preview_auto_budget_and_compacted_flag(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    cfg = EngineConfig(default_context_window=1000,
                       auto_trim_reserve_tokens=100,
                       auto_trim_output_reserve_tokens=0,
                       auto_trim_trigger_ratio=1.0)
    eng = Engine(cfg=cfg, workdir=tmp_path)
    conv = tmp_path / ".wuxing" / "conversation-a.jsonl"
    # 多轮填充：不依赖用户技能索引即可超过自动触发线（CI 空 HOME 也稳定）
    rows = [_turn(1, "第一轮" + "字" * 2000), _comp(1, 1),
            _turn(2, "第二轮" + "字" * 2000)]
    rows += [_turn(i, f"第{i}轮" + "字" * 200) for i in range(3, 11)]
    _write_rows(conv, rows)
    pv = eng.preview_session_context(conversation_path=conv)
    assert pv["budget_auto"] is True
    assert pv["budget_tokens"] > 0
    rounds = {r["round"]: r for r in pv["rounds"]}
    assert rounds[1]["compacted"] is True
    assert rounds[2]["compacted"] is False


def test_compaction_guard_shared_across_state_instances(tmp_path):
    """I2（v65）：同一 conversation 路径的两个实例共享压缩互斥。"""
    from wuxing.conversation import ConversationState

    conv = tmp_path / "conversation-a.jsonl"
    conv.write_text("", encoding="utf-8")
    a = ConversationState(conv)
    b = ConversationState(conv)
    assert a.compaction_guard() is b.compaction_guard()


def test_concurrent_compact_only_one_row_and_one_llm_call(tmp_path):
    """I2（v65）：并发压缩只有 leader 写一行/调一次模型；跟随者重读后跳过。"""
    import threading
    import time

    from wuxing.config import EngineConfig
    from wuxing.conversation import ConversationState
    from wuxing.runner import Runner
    from wuxing.trace import TraceLogger
    from wuxing.workspace import Workspace

    class SlowCompLlm(_FakeCompLlm):
        def __init__(self):
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()

        def chat(self, messages, tools=None):
            self.entered.set()
            self.release.wait(timeout=5)
            return super().chat(messages, tools)

    conv = tmp_path / ".wuxing" / "conversation-a.jsonl"
    _write_rows(conv, [_turn(1, "第一轮需求" + "x" * 30),
                       _turn(2, "第二轮需求" + "x" * 30),
                       _turn(3, "第三轮需求")])
    state_a = ConversationState(conv)
    state_b = ConversationState(conv)
    ws = Workspace(tmp_path)
    cfg = EngineConfig(auto_compact_llm_enabled=True,
                       auto_compact_keep_recent_tokens=5)
    fake = SlowCompLlm()
    trace_a = TraceLogger(tmp_path / ".wuxing" / "trace-a.jsonl")
    trace_b = TraceLogger(tmp_path / ".wuxing" / "trace-b.jsonl")
    runner_a = Runner(cfg, None, ws, fake, [], trace=trace_a,
                      conversation=state_a)
    runner_b = Runner(cfg, None, ws, fake, [], trace=trace_b,
                      conversation=state_b)
    runner_a._current_domain_id = "execute"
    runner_b._current_domain_id = "execute"
    results = []

    t1 = threading.Thread(
        target=lambda: results.append(runner_a._compact_llm_history("F-1", 10)))
    t1.start()
    assert fake.entered.wait(timeout=2)
    t2 = threading.Thread(
        target=lambda: results.append(runner_b._compact_llm_history("F-1", 10)))
    t2.start()
    time.sleep(0.2)  # 让 B 阻塞在压缩互斥上
    fake.release.set()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert not t1.is_alive() and not t2.is_alive(), "压缩互斥不得死锁"
    assert len(fake.calls) == 1, f"只应调用一次摘要模型（实际 {len(fake.calls)}）"
    rows = [t for t in state_a.turns if t.get("type") == "compaction"]
    assert len(rows) == 1, f"只应写一行压缩记录（实际 {len(rows)}）"
    assert sorted(results) == [False, True]
