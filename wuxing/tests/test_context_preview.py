"""TDD：上下文投影（B 期）——激进上界估算 + 会话/碎片分段 + 实测锚点。

设计：`docs/WUXING_上下文窗口自选_B期设计_2026-09-22.md` §2。
纪律：投影复用真实装配函数；无数据不造假；估算带 reference 标记。
"""
import json
import math
import pathlib
import typing

from wuxing.context_preview import estimate_tokens
from wuxing.conversation import ConversationState
from wuxing.engine import Engine


def _engine(tmp_path):
    return Engine(workdir=tmp_path, llm="mock", auto_confirm=True)


def test_estimate_tokens_is_cjk_aware_upper_bound():
    # 激进上界：CJK 2 tokens/char；ASCII 3 chars/token；非空文本 +8 段开销
    assert estimate_tokens("") == 0
    assert estimate_tokens("字") == 2 + 8
    assert estimate_tokens("abc") == 1 + 8
    assert estimate_tokens("汉字abc") == 4 + 1 + 8
    # 上界方向：等长 CJK 必须高于 ASCII
    assert estimate_tokens("汉" * 10) > estimate_tokens("a" * 10)


def test_preview_conversation_segments_rounds_and_missing(tmp_path):
    eng = _engine(tmp_path)
    wux = tmp_path / ".wuxing"
    wux.mkdir(parents=True, exist_ok=True)
    missing = eng.preview_session_context(conversation_path=wux / "nope.jsonl")
    assert missing["available"] is False and missing["segments"] == []

    p = wux / "conversation-1.jsonl"
    st = ConversationState(p)
    st.append_turn(1, "第一轮需求", ["a.py"], "完成1")
    st.append_turn(2, "第二轮需求", [], "完成2")
    d = eng.preview_session_context(conversation_path=p)
    assert d["available"] is True
    segs = {s["key"]: s for s in d["segments"]}
    assert segs["history"]["chars"] == len(
        st.context_text(getattr(eng.cfg, "conversation_max_chars", 4000)))
    assert [r["round"] for r in d["rounds"]] == [1, 2]
    assert all(r["omitted"] is False and r["replaced"] is False for r in d["rounds"])
    assert all(r["est_tokens"] > 0 for r in d["rounds"])   # 轮次 token 估算（非 0）
    assert d["window"] > 0
    assert d["est_tokens"] == sum(s["est_tokens"] for s in d["segments"])
    assert d["percent"] == round(d["est_tokens"] / d["window"], 4)
    # 运行期段不编数字——只列入 unknown
    assert any(u["key"] == "task_prompt" for u in d["unknown"])


def test_preview_uses_trace_measurements_and_anchor(tmp_path):
    eng = _engine(tmp_path)
    wux = tmp_path / ".wuxing"
    wux.mkdir(parents=True, exist_ok=True)
    p = wux / "conversation-1.jsonl"
    st = ConversationState(p)
    st.append_turn(1, "需求", [], "完成")
    (wux / "trace.jsonl").write_text("\n".join([
        json.dumps({"ts": 1.0, "event": "unit_started", "unit_id": "U-1",
                    "domain": "execute", "conversation_round": 1,
                    "system_chars": 3000, "skills_chars": 120}),
        json.dumps({"ts": 2.0, "event": "llm_call", "unit_id": "U-1", "round": 1,
                    "conversation_round": 1, "input": 5400, "output": 10}),
    ]) + "\n", encoding="utf-8")
    d = eng.preview_session_context(conversation_path=p)
    segs = {s["key"]: s for s in d["segments"]}
    assert segs["system"]["chars"] == 3000
    assert segs["system"]["reference"] is True           # 按上次运行实测
    assert d["anchor_tokens"] == 5400
    assert d["anchor_unit"] == "U-1"
    # 未计入的运行期段
    unknown = {u["key"] for u in d["unknown"]}
    assert {"task_prompt", "shared"} <= unknown


def test_preview_unit_session_uses_fsc_prefix(tmp_path):
    eng = _engine(tmp_path)
    wux = tmp_path / ".wuxing"
    (wux / "sessions").mkdir(parents=True, exist_ok=True)
    (wux / "sessions" / "1-P-a.jsonl").write_text("\n".join([
        json.dumps({"round": 0, "state": "seed", "ts": 1.0,
                    "messages": [{"role": "user", "content": "碎片任务"}]}),
        json.dumps({"round": 1, "state": "thinking", "ts": 2.0,
                    "messages": [{"role": "user", "content": "[tool] write: ok"}]}),
        json.dumps({"round": 1, "state": "done", "ts": 3.0, "messages": []}),
    ]) + "\n", encoding="utf-8")
    (tmp_path / ".wuxing" / "trace.jsonl").write_text(json.dumps({
        "ts": 2.0, "event": "unit_started", "unit_id": "P-a", "domain": "execute",
        "system_chars": 2800}) + "\n", encoding="utf-8")
    d = eng.preview_session_context(unit_id="P-a")
    assert d["available"] is True and d["unit_id"] == "P-a"
    segs = {s["key"]: s for s in d["segments"]}
    assert segs["fsc_prefix"]["chars"] == len("碎片任务") + len("[tool] write: ok")
    assert segs["fsc_prefix"]["reference"] is True
    assert segs["system"]["chars"] == 2800
    # A2：消息明细（index/双指纹）
    msgs = d["messages"]
    assert [m["index"] for m in msgs] == [0, 1]
    from wuxing.context_sources import content_fp
    assert msgs[0]["fp_in"] == content_fp("碎片任务")
    assert msgs[0]["fp_out"] == ""                       # 无输出侧代表
    assert msgs[1]["fp_in"] == content_fp("[tool] write: ok")
    # A2：unit 编辑（fp_in 命中）→ 前缀字符降 + 行标已省略
    side = tmp_path / ".wuxing" / "context-edits.jsonl"
    side.write_text(json.dumps({
        "kind": "unit", "unit": "P-a", "file": "1-P-a.jsonl", "index": 0,
        "fp_in": content_fp("碎片任务"), "fp_out": "",
        "op": "omit", "ts": 1}) + "\n", encoding="utf-8")
    d2 = eng.preview_session_context(unit_id="P-a")
    segs2 = {s["key"]: s for s in d2["segments"]}
    assert segs2["fsc_prefix"]["chars"] == len("[tool] write: ok")
    assert [m["omitted"] for m in d2["messages"]] == [True, False]
    # 不存在的碎片 → available=False（不造假）
    assert eng.preview_session_context(unit_id="Z-9")["available"] is False


def test_runner_trace_records_injected_segment_sizes(tmp_path):
    """Task 3：unit_started trace 记录真实注入段长（预览的实测参考数据源）。"""
    class _Llm:
        usage_history: typing.ClassVar[list] = []

        def name(self):
            return "stub"

        def spec(self):
            return "stub"

        def supports_native_tools(self):
            return False

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.usage_history.append({"input": 100, "output": 10,
                                       "cache_read": 0, "cache_write": 0})
            return ToolCallResult(text="完成声明：已完成", tool_calls=[])

    eng = Engine(workdir=tmp_path, llm=_Llm(), auto_confirm=True)
    eng.run_task("简单任务")
    trace = pathlib.Path(tmp_path / ".wuxing" / "trace.jsonl").read_text(
        encoding="utf-8")
    started = [json.loads(x) for x in trace.splitlines()
               if x.strip() and json.loads(x).get("event") == "unit_started"]
    assert started, "必须有 unit_started trace"
    row = started[0]
    assert int(row.get("system_chars") or 0) > 0
    for key in ("skills_chars", "history_chars", "digest_chars",
                "continue_chars"):
        assert key in row, f"unit_started 必须记录 {key}"
    assert int(row.get("system_est_tokens") or 0) > 0, \
        "unit_started 必须记录 system_est_tokens（预览预算映射同源数据源）"


# —— 精化（2026-09-23）：预览预算映射 —— system 实测估算 + 精确索引映射 ——

def _unit_seed(tmp_path, contents=("前缀内容甲", "前缀内容乙"), *,
               system_chars=0, system_est_tokens=None, unit_id="P-a"):
    """碎片会话 + trace 实测种子（预算映射测试用）。"""
    wux = tmp_path / ".wuxing"
    (wux / "sessions").mkdir(parents=True, exist_ok=True)
    rows = [json.dumps({"round": 0, "state": "seed", "ts": 1.0,
                        "messages": [{"role": "user", "content": c}]})
            for c in contents]
    (wux / "sessions" / f"{unit_id}.jsonl").write_text(
        "\n".join(rows) + "\n", encoding="utf-8")
    trace = {"ts": 2.0, "event": "unit_started", "unit_id": unit_id,
             "domain": "execute", "system_chars": system_chars}
    if system_est_tokens is not None:
        trace["system_est_tokens"] = system_est_tokens
    (wux / "trace.jsonl").write_text(json.dumps(trace) + "\n", encoding="utf-8")


def _unit_budget(tmp_path, budget, unit_id="P-a"):
    from wuxing.context_sources import save as _save
    _save(tmp_path, "units", unit_id, {"budget_tokens": int(budget)})


def _skills_est(eng) -> int:
    """当前引擎技能索引段的 token 估算（预算参与项——测试算式用）。"""
    from wuxing.prompt_builder import build_skill_index_msg
    msg = build_skill_index_msg(eng.skills)
    if msg is None:
        return 0
    return estimate_tokens(str(msg.get("content") or ""))


def test_preview_unit_budget_uses_measured_system_tokens(tmp_path):
    """system 有实测估算 → 预算映射按其计数（旧 ASCII 占位会漏裁）。"""
    eng = _engine(tmp_path)
    _unit_seed(tmp_path, system_chars=200, system_est_tokens=200)
    # 实测 200 + 两前缀 18+18 + 未提交任务 22 + 技能 sk；预算 = 总量−18 → 恰裁最旧一条
    total = 200 + 18 + 18 + 22 + _skills_est(eng)
    _unit_budget(tmp_path, total - 18)
    d = eng.preview_session_context(unit_id="P-a")
    assert any(t["key"] == "prefix" for t in d["trimmed"]), d["trimmed"]
    segs = {s["key"]: s for s in d["segments"]}
    assert segs["fsc_prefix"]["chars"] == len("前缀内容乙")


def test_preview_unit_budget_respects_measured_small_system(tmp_path):
    """实测估算偏小（ASCII 模板）→ 不得回退用系统上限（×2）高估。"""
    eng = _engine(tmp_path)
    _unit_seed(tmp_path, system_chars=200, system_est_tokens=110)
    # 实测 110（非上限 408）+ 18+18+22+sk = 预算 → 不裁
    _unit_budget(tmp_path, 110 + 18 + 18 + 22 + _skills_est(eng))
    d = eng.preview_session_context(unit_id="P-a")
    assert d["trimmed"] == []
    segs = {s["key"]: s for s in d["segments"]}
    assert segs["fsc_prefix"]["chars"] == 10


def test_preview_unit_budget_fallback_uses_system_upper_bound(tmp_path):
    """无实测估算（旧 trace）→ system 占位按 CJK 上界（×2），不得用 ASCII 低估。"""
    eng = _engine(tmp_path)
    _unit_seed(tmp_path, system_chars=200)      # 无 system_est_tokens
    # 上限 2×200+8=408；预算 = 408+18+18+22+sk−18 → 恰裁最旧一条
    total = 408 + 18 + 18 + 22 + _skills_est(eng)
    _unit_budget(tmp_path, total - 18)
    d = eng.preview_session_context(unit_id="P-a")
    assert any(t["key"] == "prefix" for t in d["trimmed"]), d["trimmed"]
    segs = {s["key"]: s for s in d["segments"]}
    assert segs["fsc_prefix"]["chars"] == len("前缀内容乙")


def test_preview_unit_budget_maps_duplicates_by_index(tmp_path):
    """同内容消息按原始索引精确映射（不得按值把已裁条保留）。"""
    eng = _engine(tmp_path)
    _unit_seed(tmp_path, contents=("重复内容", "重复内容"))
    # 16+16+22+sk；预算 = 总量−16 → 恰裁首条（旧值匹配会两条都保留）
    total = 16 + 16 + 22 + _skills_est(eng)
    _unit_budget(tmp_path, total - 16)
    d = eng.preview_session_context(unit_id="P-a")
    assert any(t["key"] == "prefix" for t in d["trimmed"]), d["trimmed"]
    segs = {s["key"]: s for s in d["segments"]}
    assert segs["fsc_prefix"]["chars"] == len("重复内容")


class _StubSkills:
    def __init__(self, idx):
        self._idx = idx

    def index(self):
        return self._idx


def test_preview_unit_budget_counts_real_skills_text(tmp_path):
    """技能段按真实文本计数（旧 ASCII 占位低估 → 漏裁）。"""
    eng = _engine(tmp_path)
    eng.skills = _StubSkills({"demo": {"level": "user",
                                       "description": "中文技能描述" * 3}})
    _unit_seed(tmp_path)
    from wuxing.prompt_builder import build_skill_index_msg
    text = str(build_skill_index_msg(eng.skills)["content"])
    ascii_est = math.ceil(len(text) / 3) + 8        # 旧占位（"x"*len）
    real_est = estimate_tokens(text)
    assert real_est > ascii_est + 8, "测试前提：技能文本 CJK 占比高"
    # 58（前缀+prompt） + ascii_est 可容 → 实文本才超预算
    _unit_budget(tmp_path, 58 + ascii_est + 4)
    d = eng.preview_session_context(unit_id="P-a")
    assert any(t["key"] == "prefix" for t in d["trimmed"]), d["trimmed"]


def test_preview_conversation_budget_uses_measured_system_tokens(tmp_path):
    """主会话预览同口径：system 实测估算参与预算（旧 ASCII 占位漏裁历史）。"""
    eng = _engine(tmp_path)
    wux = tmp_path / ".wuxing"
    wux.mkdir(parents=True, exist_ok=True)
    p = wux / "conversation-1.jsonl"
    st = ConversationState(p)
    st.append_turn(1, "第一轮需求内容", [], "完成1")
    st.append_turn(2, "第二轮需求内容", [], "完成2")
    (wux / "trace.jsonl").write_text(json.dumps({
        "ts": 2.0, "event": "unit_started", "unit_id": "U-1",
        "domain": "execute", "conversation_round": 2,
        "system_chars": 200, "system_est_tokens": 200}) + "\n",
        encoding="utf-8")
    d0 = eng.preview_session_context(conversation_path=p)
    segs0 = {s["key"]: s for s in d0["segments"]}
    assert "digest" not in segs0                       # 前提：无回退摘要段
    hist = st.context_text(getattr(eng.cfg, "conversation_max_chars", 4000))
    skills_est = int(segs0.get("skills", {}).get("est_tokens", 0))
    old_sys = math.ceil(200 / 3) + 8                   # 旧 ASCII 占位口径
    budget = (old_sys + estimate_tokens(hist) + skills_est
              + estimate_tokens("（未提交任务）") + 10)
    from wuxing.context_sources import save as _save
    _save(tmp_path, "conversations", p.name, {"budget_tokens": budget})
    d = eng.preview_session_context(conversation_path=p)
    assert any(t["key"] == "history" for t in d["trimmed"]), d["trimmed"]


def test_fill_tokens_estimates_exactly_requested():
    """预算占位文本：estimate_tokens 恰为请求值（镜像真实计数）。"""
    from wuxing.context_preview import _fill_tokens
    assert _fill_tokens(0) == ""
    for tokens in range(9, 41):
        assert estimate_tokens(_fill_tokens(tokens)) == tokens, tokens
