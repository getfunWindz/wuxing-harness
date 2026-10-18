"""E2-2（G7 修订 v2）：触发公式/保留封顶/事务纪律/压缩纪律。

设计权威：`docs/WUXING_自动压缩_G7_设计_2026-09-26.md` §11。
"""
import json


def _cfg(**kw):
    from wuxing.config import EngineConfig
    base = {"auto_trim_enabled": True, "auto_trim_reserve_tokens": 1000,
            "auto_trim_output_reserve_tokens": 500,
            "auto_trim_trigger_ratio": 0.8,
            "auto_compact_keep_recent_tokens": 20000}
    base.update(kw)
    return EngineConfig(**base)


# ---- T1：触发公式与保留封顶（B2）----

def test_trigger_formula_ratio_and_headroom():
    from wuxing.context_budget import auto_trigger_budget
    assert auto_trigger_budget(_cfg(), 10000) == 8000     # min(0.8W=8000, W−O−B=8500)
    assert auto_trigger_budget(_cfg(), 20000) == 16000    # min(16000, 18500)
    assert auto_trigger_budget(_cfg(), 2000) == 500       # min(1600, 500)
    assert auto_trigger_budget(_cfg(), 1400) == 0         # W−O−B < 0 → 禁用
    assert auto_trigger_budget(_cfg(auto_trim_trigger_ratio=1.5), 10000) == 0
    assert auto_trigger_budget(_cfg(auto_trim_enabled=False), 10000) == 0


def test_keep_recent_ratio_cap():
    from wuxing.context_budget import effective_keep_recent
    assert effective_keep_recent(_cfg(), 200_000) == 20000      # 封顶 30689 → 绝对 20000
    assert effective_keep_recent(_cfg(), 64_000) == 10160       # (64000−500)×0.16
    assert effective_keep_recent(_cfg(), 0) == 20000            # 窗口未知 → 绝对


def test_new_config_keys_doublewrite_and_validation():
    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS, validate_config
    cfg = EngineConfig()
    assert cfg.auto_trim_trigger_ratio == 0.8
    assert cfg.auto_trim_output_reserve_tokens == 8192
    spec = {s.name: s for s in FIELD_SPECS}
    assert spec["auto_trim_trigger_ratio"].default == 0.8
    assert spec["auto_trim_output_reserve_tokens"].default == 8192
    assert validate_config({"auto_trim_trigger_ratio": 0})       # (0,1] 外
    assert validate_config({"auto_trim_trigger_ratio": 1.5})
    assert validate_config({"auto_trim_output_reserve_tokens": -1})
    assert validate_config({"auto_trim_trigger_ratio": 0.5}) == []


# ---- T2：事务纪律（不缩小拒绝 / 幂等 / 文件累计） ----

def _turn_row(rnd, text, arts=()):
    return {"round": rnd, "user_text": text, "artifacts": list(arts),
            "summary": "done", "ts": 1000.0 + rnd}


def _comp_runner(tmp_path, llm, keep=5):
    from wuxing.config import EngineConfig
    from wuxing.conversation import ConversationState
    from wuxing.runner import Runner
    from wuxing.trace import TraceLogger
    from wuxing.workspace import Workspace
    ws = Workspace(tmp_path)
    trace = TraceLogger(tmp_path / ".wuxing" / "trace.jsonl")
    cfg = EngineConfig(auto_compact_llm_enabled=True,
                       auto_compact_keep_recent_tokens=keep,
                       auto_trim_output_reserve_tokens=0)
    conv = tmp_path / ".wuxing" / "conversation-a.jsonl"
    rows = [_turn_row(1, "第一轮需求" * 10, ["a.py"]),
            _turn_row(2, "第二轮需求" * 10, ["b.py"]),
            _turn_row(3, "第三轮", [])]
    conv.parent.mkdir(parents=True, exist_ok=True)
    conv.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                              for r in rows) + "\n", encoding="utf-8")
    state = ConversationState(conv)
    runner = Runner(cfg, None, ws, llm, [], trace=trace, conversation=state)
    runner._current_domain_id = "execute"
    return runner, state, trace


class _FakeLlm:
    def __init__(self, text="COMPACTED"):
        self.text = text
        self.calls = []
        self.tools_args = []

    def spec(self):
        return "deepseek:fake"

    def name(self):
        return "fake"

    def chat(self, messages, tools=None):
        self.calls.append(messages)
        self.tools_args.append(tools)
        return self.text


def test_compact_rejects_non_shrinking_summary(tmp_path):
    fake = _FakeLlm("巨" * 20000)   # 比源内容大得多
    runner, state, trace = _comp_runner(tmp_path, fake)
    assert runner._compact_llm_history("F-1", 10) is False
    assert state.last_compaction() is None
    rows = [r for r in trace.load() if r["event"] == "compaction_rejected"]
    assert rows and rows[-1]["reason"] == "not-shrinking"


def test_compact_idempotent_and_details_accumulate(tmp_path):
    fake = _FakeLlm("摘要")
    runner, state, _trace = _comp_runner(tmp_path, fake)
    assert runner._compact_llm_history("F-1", 10) is True
    comp = state.last_compaction()
    assert comp["details"]["files"] == ["a.py", "b.py"]
    # 无新轮 → 幂等（不重写第二行）
    assert runner._compact_llm_history("F-1", 10) is False
    assert len([t for t in state.turns if t.get("type") == "compaction"]) == 1
    # 新轮 + 新文件 → 累计 union，from 沿用
    state.append_turn(state.round_no + 1, "第四轮需求" * 10, ["c.py"])
    assert runner._compact_llm_history("F-1", 10) is True
    comp2 = state.last_compaction()
    assert comp2["from_round"] == 1
    assert comp2["details"]["files"] == ["a.py", "b.py", "c.py"]


def test_compact_range_is_contiguous_rounds(tmp_path):
    fake = _FakeLlm("摘要")
    runner, state, _trace = _comp_runner(tmp_path, fake)
    assert runner._compact_llm_history("F-1", 10) is True
    comp = state.last_compaction()
    rounds = {t.get("round") for t in state.turns if "round" in t}
    covered = set(range(comp["from_round"], comp["to_round"] + 1))
    assert covered <= rounds            # 覆盖范围=连续存在的轮（不产生空洞）


def test_summary_call_is_bare_user_message(tmp_path):
    """B4 定策：摘要调用不带 system/工具段（适配器不打 cache_control）。"""
    fake = _FakeLlm("摘要")
    runner, _state, _trace = _comp_runner(tmp_path, fake)
    assert runner._compact_llm_history("F-1", 10) is True
    assert fake.calls and len(fake.calls[-1]) == 1
    assert fake.calls[-1][0]["role"] == "user"
    assert fake.tools_args[-1] is None


# ---- T3：溢出恢复（判据/配对安全/一次重试） ----

def test_is_context_overflow_error():
    from wuxing.repairer import is_context_overflow_error
    assert is_context_overflow_error(
        RuntimeError("This model's maximum context length is 65536 tokens")) is True
    assert is_context_overflow_error(RuntimeError("connection reset")) is False


def test_trim_oldest_chunks_pairing_safe():
    from wuxing.context_budget import trim_oldest_chunks
    msgs = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "[会话历史]\n" + "旧" * 100},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}]},
        {"role": "tool", "content": "结果" * 100},
        {"role": "user", "content": "当前任务"},
    ]
    out, removed, chars = trim_oldest_chunks(msgs, budget_tokens=10, estimator=len)
    assert removed == 1 and chars > 0
    assert [m["role"] for m in out] == ["system", "user"]
    assert out[-1]["content"] == "当前任务"


class _OverflowThenOk:
    def __init__(self, fail_times=1):
        self.fail_times = fail_times
        self.n = 0

    def name(self):
        return "fake"

    def spec(self):
        return "deepseek:fake"

    def chat(self, messages, tools=None):
        self.n += 1
        if self.n <= self.fail_times:
            raise RuntimeError(
                "This model's maximum context length is 1024 tokens")
        return "RECOVERED"


def _overflow_runner(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.runner import Runner
    from wuxing.trace import TraceLogger
    from wuxing.workspace import Workspace
    ws = Workspace(tmp_path)
    trace = TraceLogger(tmp_path / ".wuxing" / "trace.jsonl")
    runner = Runner(EngineConfig(), None, ws, None, [], trace=trace)
    runner._current_domain_id = "execute"
    runner._tool_schemas = []          # run_unit 正常路径会初始化（夹具补齐）
    runner._messages = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "[会话历史]\n" + "旧" * 500},
        {"role": "user", "content": "当前任务"},
    ]
    return runner, trace


def test_overflow_recovery_retries_once(tmp_path):
    runner, trace = _overflow_runner(tmp_path)
    llm = _OverflowThenOk()
    assert runner._chat_with_tools(llm) == "RECOVERED"
    assert llm.n == 2
    rows = [r for r in trace.load()
            if r["event"] == "context_overflow_recovery"]
    assert rows and rows[-1]["chunks"] == 1


def test_overflow_non_overflow_error_raises(tmp_path):
    import pytest
    runner, _ = _overflow_runner(tmp_path)

    class _Boom:
        def name(self):
            return "fake"

        def spec(self):
            return "x:y"

        def chat(self, messages, tools=None):
            raise RuntimeError("connection reset")

    with pytest.raises(RuntimeError):
        runner._chat_with_tools(_Boom())


def test_overflow_without_removable_chunks_raises(tmp_path):
    import pytest
    runner, _ = _overflow_runner(tmp_path)
    runner._messages = [{"role": "system", "content": "S"},
                        {"role": "user", "content": "当前任务"}]
    with pytest.raises(RuntimeError):
        runner._chat_with_tools(_OverflowThenOk(fail_times=99))


# ---- 真跑实证连带修复（2026-10-03）：enforce_budget 前缀删除后索引位移 ----

def test_enforce_budget_prompt_survives_prefix_deletion_shift():
    """回归：删历史后 prompt 顶到旧索引，keep 旧索引失效 → 误删当前 prompt。

    真跑实证（E2-2 小窗口实验）：input 仅剩 system → DeepSeek /responses
    报 400 "Input items array must not be empty"。修复：keep 改按对象身份
    （id）判定 + 最后一条 user 无条件保护。
    """
    from wuxing.context_budget import enforce_budget
    msgs = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "[会话历史]\n" + "旧" * 200},
        {"role": "user", "content": "任务背景：当前任务"},
    ]
    out, _trimmed = enforce_budget(msgs, 5, len)
    assert [m["role"] for m in out] == ["system", "user"], out
    assert out[-1]["content"].startswith("任务背景：")
