"""TDD：P1 T1 usage 真值标准化（债 1——服务端缓存可度量）。

知识库「服务端提示缓存」：DeepSeek `prompt_cache_hit_tokens`、Anthropic
`cache_read_input_tokens`、OpenAI `prompt_tokens_details.cached_tokens`
→ 统一 {input, output, cache_read, cache_write}。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.anthropic import AnthropicProvider
from wuxing.llm.openai import OpenAIChatProvider
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class FakeResp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        pass

    def json(self):
        return self._c


class CaptureHttp:
    def __init__(self, payload):
        self._payload = payload

    def post(self, url, **kw):
        return FakeResp(self._payload)


def test_deepseek_usage_parsed_to_standard():
    """DeepSeek 格式：prompt_cache_hit_tokens → cache_read。"""
    payload = {"choices": [{"message": {"role": "assistant", "content": "ok"}}],
               "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                         "prompt_cache_hit_tokens": 60,
                         "prompt_cache_miss_tokens": 40}}
    p = OpenAIChatProvider(api_key="k", _http=CaptureHttp(payload))
    p.chat([{"role": "user", "content": "hi"}])
    u = p.usage_history[-1]
    # DeepSeek 官方口径（2026-09-10）：cache_miss 直接来自 API（fixture 未提供则省略）
    assert u["input"] == 100 and u["output"] == 20, u
    assert u["cache_read"] == 60 and u["cache_write"] == 0, u
    assert u.get("cache_miss") == 40, "官方 miss 字段必须解析（fixture 提供）"


def test_deepseek_miss_derived_when_absent():
    """兜底（2026-09-11）：当响应缺 prompt_cache_miss_tokens（部分 OpenAI
    兼容通道不返回该字段）时，按官方恒等式推导 miss = prompt_tokens - hit
    （官方文档：prompt_tokens = prompt_cache_hit_tokens + prompt_cache_miss_tokens）。

    注：DeepSeek 官方响应含该字段；此前 trace 缺失系旧代码版本未解析
    （2026-09-11 复核更正）——本测试锁定缺失场景的推导行为。"""
    payload = {"choices": [{"message": {"role": "assistant", "content": "ok"}}],
               "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                         "prompt_cache_hit_tokens": 60}}
    p = OpenAIChatProvider(api_key="k", _http=CaptureHttp(payload))
    p.chat([{"role": "user", "content": "hi"}])
    u = p.usage_history[-1]
    assert u.get("cache_miss") == 40, f"miss 必须由恒等式推导（实际 {u}）"


def test_openai_details_cached_tokens_miss_derived():
    """OpenAI details 路径同样推导 miss（prompt_tokens_details.cached_tokens）。"""
    payload = {"choices": [{"message": {"role": "assistant", "content": "ok"}}],
               "usage": {"prompt_tokens": 50, "completion_tokens": 10,
                         "prompt_tokens_details": {"cached_tokens": 30}}}
    p = OpenAIChatProvider(api_key="k", _http=CaptureHttp(payload))
    p.chat([{"role": "user", "content": "hi"}])
    u = p.usage_history[-1]
    assert u.get("cache_miss") == 20, f"details 路径 miss 必须推导（实际 {u}）"


def test_openai_cached_tokens_parsed():
    """OpenAI 官方格式：prompt_tokens_details.cached_tokens → cache_read。"""
    payload = {"choices": [{"message": {"role": "assistant", "content": "ok"}}],
               "usage": {"prompt_tokens": 50, "completion_tokens": 10,
                         "prompt_tokens_details": {"cached_tokens": 30}}}
    p = OpenAIChatProvider(api_key="k", _http=CaptureHttp(payload))
    p.chat([{"role": "user", "content": "hi"}])
    u = p.usage_history[-1]
    assert u["cache_read"] == 30 and u["input"] == 50


def test_anthropic_cache_read_parsed():
    """Anthropic 格式：cache_read_input_tokens / cache_creation_input_tokens。

    B 级修复（2026-09-11）：input 统一为总输入（input_tokens + 读 + 写）——
    与 DeepSeek prompt_tokens 口径一致（命中率 ≤1、成本估算不为负）。
    """
    payload = {"content": [{"type": "text", "text": "ok"}],
               "usage": {"input_tokens": 80, "output_tokens": 15,
                         "cache_read_input_tokens": 55,
                         "cache_creation_input_tokens": 25}}
    p = AnthropicProvider(api_key="k", _http=CaptureHttp(payload))
    p.chat([{"role": "user", "content": "hi"}])
    u = p.usage_history[-1]
    assert u == {"input": 160, "output": 15, "cache_read": 55,
                 "cache_write": 25}, u


def test_usage_missing_tolerated():
    """响应无 usage 字段：容错为 0（真值缺失不崩溃）。"""
    payload = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
    p = OpenAIChatProvider(api_key="k", _http=CaptureHttp(payload))
    p.chat([{"role": "user", "content": "hi"}])
    assert p.usage_history[-1] == {"input": 0, "output": 0,
                                   "cache_read": 0, "cache_write": 0}


def test_usage_aggregate_keeps_optional_fields():
    """聚合不得丢弃可选真值（2026-09-11）：cache_miss 与 reasoning_tokens
    必须进入单元/任务级 usage 汇总（否则报告/评测看不到——此前被静默丢弃）。"""
    from wuxing.usage_tracker import UsageTracker
    used = [{"input": 100, "output": 10, "cache_read": 60, "cache_write": 0,
             "cache_miss": 40, "reasoning_tokens": 30},
            {"input": 50, "output": 5, "cache_read": 0, "cache_write": 0}]
    agg = UsageTracker.aggregate(used)
    assert agg["cache_miss"] == 40, agg
    assert agg["reasoning_tokens"] == 30, agg


def test_engine_metrics_keep_optional_usage():
    """任务级 metrics.usage 必须保留 cache_miss / reasoning_tokens（可选真值）。"""
    import pathlib
    import tempfile

    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    u = UnitResult(unit_id="U-1", domain_id="execute", status="ok")
    u.metrics = {"llm_calls": 2, "usage": {
        "input": 300, "output": 30, "cache_read": 180, "cache_write": 0,
        "cache_miss": 120, "reasoning_tokens": 90}}
    m = eng._collect_metrics([u], eng._cache_snapshot())
    assert m["usage"]["cache_miss"] == 120, m["usage"]
    assert m["usage"]["reasoning_tokens"] == 90, m["usage"]


class UsageProbeLlm:
    """带 usage_history 的假 LLM（模拟真 provider）。"""

    def __init__(self):
        self.usage_history = [
            {"input": 100, "output": 20, "cache_read": 60, "cache_write": 0},
            {"input": 90, "output": 15, "cache_read": 90, "cache_write": 0},
        ]

    def name(self):
        return "usageprobe"


class PlainTextLlm:
    """无 usage 属性的旧假 LLM（兼容路径）。"""

    def name(self):
        return "plain"


def test_runner_metrics_aggregate_usage():
    """单元级：UnitResult.metrics 含 llm_calls/usage 汇总（快照区间）。"""
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))

    class LoopLlm(UsageProbeLlm):
        def __init__(self):
            super().__init__()
            self.base = len(self.usage_history)

        def chat(self, messages, tools=None):
            self.usage_history.append({"input": 50, "output": 5,
                                       "cache_read": 0, "cache_write": 0})
            from wuxing.llm.tool_results import ToolCallResult
            return ToolCallResult(text="方案：完整执行计划", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "p.md", "kind": "plan", "content": "x"}}])

    llm = LoopLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok"
    m = res.metrics
    assert m["llm_calls"] >= 1, m
    assert m["usage"]["input"] >= 50, m  # 仅本次新增调用计入


def test_runner_metrics_plain_llm_zero():
    """假 LLM 无 usage_history：metrics 兜底 0（不崩）。"""
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))

    class PlainLlm(PlainTextLlm):
        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            return ToolCallResult(text="方案：完整执行计划", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "p.md", "kind": "plan", "content": "x"}}])

    r = Runner(cfg, DomainRegistry(cfg), ws, PlainLlm(), load_tools(ws))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok"
    assert res.metrics["usage"] == {"input": 0, "output": 0,
                                    "cache_read": 0, "cache_write": 0}


def test_unit_metrics_include_usage_latest():
    """CH 口径（用户裁决 2026-10-02）：单元 metrics 带最近一次请求 usage。"""
    class LoopLlm(UsageProbeLlm):
        def __init__(self):
            super().__init__()
            self.base = len(self.usage_history)

        def chat(self, messages, tools=None):
            self.usage_history.append({"input": 50, "output": 5,
                                       "cache_read": 40, "cache_write": 0})
            from wuxing.llm.tool_results import ToolCallResult
            return ToolCallResult(text="方案：完整执行计划", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "p.md", "kind": "plan", "content": "x"}}])

    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, LoopLlm(), load_tools(ws))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok"
    latest = res.metrics.get("usage_latest")
    assert isinstance(latest, dict), res.metrics
    assert latest["input"] >= 50, latest
    assert res.metrics.get("usage_latest_ts") is not None


def test_engine_metrics_usage_latest_picks_most_recent():
    """任务级 metrics：usage_latest 取时间戳最新的单元（CH 口径）。"""
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    u1 = UnitResult(unit_id="U-1", domain_id="execute", status="ok")
    u1.metrics = {"llm_calls": 1,
                  "usage": {"input": 100, "output": 5,
                            "cache_read": 40, "cache_write": 0},
                  "usage_latest": {"input": 100, "output": 5,
                                    "cache_read": 40, "cache_write": 0},
                  "usage_latest_ts": 10.0}
    u2 = UnitResult(unit_id="U-2", domain_id="verify", status="ok")
    u2.metrics = {"llm_calls": 1,
                  "usage": {"input": 200, "output": 8,
                            "cache_read": 180, "cache_write": 0},
                  "usage_latest": {"input": 200, "output": 8,
                                    "cache_read": 180, "cache_write": 0},
                  "usage_latest_ts": 20.0}
    m = eng._collect_metrics([u1, u2], eng._cache_snapshot())
    assert m["usage_latest"] == {"input": 200, "output": 8,
                                 "cache_read": 180, "cache_write": 0}
