"""TDD：核心闭环测试（P0 审查报告 S1/S2——工具结果回填 + 缓存不毒化）。

测试纪律（审查报告 §A8）：第二轮 messages 必须包含工具结果——旧假 LLM
（有状态脚本化）掩盖了无反馈缺陷，本文件测试的是「消息内容」而非「脚本行为」。
"""
import pathlib
import tempfile

from wuxing.cache import ReplyCache
from wuxing.config import EngineConfig
from wuxing.llm.tool_results import ToolCallResult
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class RecordingLlm:
    """记录每次调用收到的 messages（断言消息内容用，非脚本化行为）。"""

    def __init__(self, converged_text: str):
        self.calls = 0
        self.seen = []
        self._converged_text = converged_text

    def name(self):
        return "recording"

    def chat(self, messages, tools=None):
        self.calls += 1
        self.seen.append([dict(m) for m in messages])
        if self.calls == 1:
            # 第一轮：调用工具，但文本不含 marker（真实模型常见——先干后说）
            return ToolCallResult(text="我先调用工具检查依赖", tool_calls=[
                {"name": "load_skill",
                 "arguments": {"skill_name": "no-such"}}])
        # 第二轮：若能看到工具结果则收敛（判定逻辑在测试断言里）
        return ToolCallResult(text=self._converged_text, tool_calls=[])


def _make_runner(llm, reply_cache=None):
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    return Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws),
                  reply_cache=reply_cache)


def test_tool_results_fed_back_next_round():
    """S1：第二轮 messages 必须包含第一轮工具执行结果。"""
    llm = RecordingLlm("方案：完整执行计划")
    r = _make_runner(llm)
    res = r.run_unit("U-1", "plan", {"goal": "plan:写方案"})
    assert res.status == "ok"
    assert llm.calls == 2, "第二轮必须真正调用 LLM（未被缓存毒化）"
    # 核心断言：第二轮看到的消息里包含工具结果（written a.md）
    second = " ".join(m["content"] for m in llm.seen[1]
                      if isinstance(m.get("content"), str))
    assert "技能注册表未装配" in second, f"第二轮 messages 无工具结果：{second!r}"
    assert "tool:error" in second or "guard" in second  # 工具结果语义可见


def test_cache_not_poisoned_within_unit():
    """S2：带 ReplyCache 时，单元内第二轮不得命中缓存（同键毒化修复）。"""
    llm = RecordingLlm("方案：完整执行计划")
    rc = ReplyCache(pathlib.Path(tempfile.mkdtemp()) / "rc.json")
    r = _make_runner(llm, reply_cache=rc)
    res = r.run_unit("U-1", "plan", {"goal": "plan:写方案"})
    assert res.status == "ok", f"应收敛而非预算耗尽：{res.error}"
    assert llm.calls == 2, "LLM 必须在第二轮被真正调用"
    assert rc.hits == 0, f"单元内轮次不得命中缓存（hits={rc.hits}）——同键毒化应已消除"
    assert rc.misses == 1, "仅首轮查询缓存（miss=1）"


def test_rounds_append_llm_output_to_history():
    """T1-3：第二轮 messages 包含第一轮 LLM 文本输出（历史积累）。"""
    llm = RecordingLlm("方案：完整执行计划")
    r = _make_runner(llm)
    res = r.run_unit("U-1", "plan", {"goal": "plan:写方案"})
    assert res.status == "ok"
    second = " ".join(m["content"] for m in llm.seen[1]
                      if isinstance(m.get("content"), str))
    assert "我先调用工具" in second, "第一轮 LLM 输出必须进入第二轮历史"
