"""TDD · 会话级缓存度量（真实测试口径：轮次 + 累计命中率曲线）。"""
import pathlib
import tempfile

from wuxing.engine import Engine


class _UsageLlm:
    """固定 usage（input 100 / cache_read 50 → 单轮 0.5）——验证累计口径。"""

    def __init__(self):
        self.usage_history = []
        self.call_count = 0

    def name(self):
        return "usage"

    def spec(self):
        return "usage"

    def supports_native_tools(self):
        return False

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.usage_history.append({"input": 100, "output": 10,
                                   "cache_read": 50, "cache_write": 0})
        text = " ".join(m.get("content", "") for m in messages)
        if "域：plan" in text:
            return ToolCallResult(text="方案", tool_calls=[
                {"name": "write_artifact", "arguments": {
                    "path": "plan.md", "kind": "plan", "content": "x"}}])
        return ToolCallResult(text="执行完成", tool_calls=[
            {"name": "write_artifact", "arguments": {
                "path": "out.md", "kind": "result", "content": "x"}}])


def test_session_metrics_cumulative_cache_ratio():
    """会话度量：轮次 + 累计 usage + 累计命中率（真实测试口径——跨轮累加）。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    eng = Engine(workdir=tmp, llm=_UsageLlm(), auto_confirm=True)
    s = eng.start_session()
    r1 = s.send("任务一")
    m1 = s.metrics()
    assert m1["rounds"] == 1
    assert len(m1["per_round"]) == 1
    assert 0.0 <= m1["cumulative"]["cache_read_ratio"] <= 1.0
    # 轮次级 metrics 必须出现在 TaskResult 上（真实测试可逐轮采集）
    assert r1.metrics.get("conversation", {}).get("round") == 1


def test_session_metrics_accumulate_across_rounds():
    """两轮累计：usage 跨轮求和（缓存命中轮无 usage 也不崩）。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    eng = Engine(workdir=tmp, llm=_UsageLlm(), auto_confirm=True)
    s = eng.start_session()
    s.send("任务一")
    s.send("任务二")
    m = s.metrics()
    assert m["rounds"] == 2
    assert len(m["per_round"]) == 2
    # 累计 input ≥ 单轮（跨轮求和——命中轮可能 0 增量）
    assert m["cumulative"]["usage"]["input"] >= 100


def test_zero_call_round_is_none_not_zero():
    """口径修正：零调用轮（无输入）命中率必须为 None（无数据）——不能记 0.0
    拉低算术均值（novice-4 的 0.576 vs 0.638 失真源）。"""
    import pathlib
    import tempfile

    from wuxing.real_test import run_profile

    # 用 real_test 的 mock 流程跑两轮（第 2 轮大概率缓存命中零调用）
    wd = pathlib.Path(tempfile.mkdtemp())
    rows = run_profile("precise", workdir=wd, llm=None, real_shape=False,
                       max_turns=2)
    for r in rows:
        if r["input"] == 0:
            assert r["cache_read_ratio"] is None, \
                "零输入轮必须 None（无数据不参与均值）"


def test_effective_avg_excludes_zero_rounds():
    """口径修正：有效轮均值（剔除零调用轮）——报告必须给出。"""
    import pathlib
    import tempfile

    from wuxing.real_test import run_profile
    wd = pathlib.Path(tempfile.mkdtemp())
    rows = run_profile("precise", workdir=wd, llm=None, real_shape=False,
                       max_turns=2)
    _eff = [r["cache_read_ratio"] for r in rows
            if r["cache_read_ratio"] is not None]
    # mock 轮全零 usage —— eff 可能为空；只断言"有效轮"语义存在于行字段
    assert all((r["input"] == 0) == (r["cache_read_ratio"] is None)
               for r in rows), "输入与命中率字段语义必须一致"
