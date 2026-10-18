"""TDD · L2-4：失败重试链（FC 层3——校验重试兜底；Repairer 文案级→指令级）。

知识库「FunctionCalling 三层」层3：调用失败重试 + 错误回填——本层：
- classify_failure 识别 param 类（参数错误——L2-2 校验产生）
- repair_hint 结构化指令 {action, hint}（替代纯文案——可测可归因）
- Runner 挂钩：工具错误后下一轮注入修正指令（模型可见——非文案空转）
"""
import pathlib
import tempfile

from wuxing.repairer import classify_failure, repair_hint


def test_classify_param_failure():
    """L2-4：param: 前缀 → param 类（参数错误——FC 层1 校验输出）。"""
    assert classify_failure("param: missing required: path") == "param"


def test_repair_hint_mapping():
    """L2-4：五类失败 → 结构化指令（action 语义化——指令级而非文案级）。"""
    assert repair_hint("param", "param: missing required: path") == {
        "action": "fix_params",
        "hint": "参数错误：param: missing required: path —— 按工具 schema 修正参数后重试"}
    assert repair_hint("tool", "mcp echo: timeout")["action"] == "switch_tool"
    assert repair_hint("contract", "契约不符合")["action"] == "fix_output"
    assert repair_hint("budget", "预算耗尽")["action"] == "converge"
    assert repair_hint("provider", "505")["action"] == "retry"
    assert repair_hint("unknown", "x")["action"] == "stop"


def test_repair_hint_backfilled_to_model():
    """Runner 集成：工具参数错误 → 下一轮上下文含修正指令（层3 兜底闭环）。"""
    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.base import ToolRegistry
    from wuxing.tools.builtin import BUILTIN_TOOLS
    from wuxing.workspace import Workspace

    class ProbeLlm:
        def __init__(self):
            self.calls = 0
            self.seen = []

        def name(self):
            return "probe"

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.calls += 1
            self.seen.append([dict(m) for m in messages])
            if self.calls == 1:
                return ToolCallResult(text="", tool_calls=[
                    {"name": "write_artifact",
                     "arguments": {"content": "x"}}])  # 缺 path → param 错误
            return "方案：完整执行计划"

    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = ProbeLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, ToolRegistry(BUILTIN_TOOLS(ws)))
    r.run_unit("U-1", "plan", {"goal": "x"})
    second = " ".join(m["content"] for m in llm.seen[1]
                      if isinstance(m.get("content"), str))
    assert "修正指令" in second and "参数错误" in second, \
        f"修正指令必须回填模型：{second[-300:]!r}"
