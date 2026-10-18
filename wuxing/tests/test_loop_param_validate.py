"""TDD · L2-2：工具参数校验（FC 层1 约束——调用前 schema 校验 + 错误回填）。

知识库「FunctionCalling 稳定三层」：约束（防错）→ 检索（选准）→ 重试（兜底）。
本层：required 缺失/类型不符 → 结构化 error（不吞错——模型下一轮可见）。
"""
import pathlib
import tempfile

from wuxing.tools.base import ToolRegistry
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


def _registry():
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    return ToolRegistry(BUILTIN_TOOLS(ws))


def test_missing_required_rejected():
    """缺 required 字段 → error（param: 前缀 + 字段名——可归因）。"""
    r = _registry()
    res = r.execute("write_artifact", content="x")  # 缺 path
    assert res.status == "error", "缺参必须拦截（FC 层1 约束）"
    assert "param:" in res.error and "path" in res.error, res.error


def test_wrong_type_rejected():
    """类型不符 → error（content 应 str——传 dict 拦截）。"""
    r = _registry()
    res = r.execute("write_artifact", path="p.md", kind="plan",
                    content={"bad": "x"})
    assert res.status == "error"
    assert "content" in res.error and "param:" in res.error


def test_valid_call_unchanged():
    """合法调用不受影响（零误伤——现有行为保持）。"""
    r = _registry()
    res = r.execute("write_artifact", path="p.md", kind="plan", content="x")
    assert res.status == "ok", res.error


def test_param_error_backfilled_to_model():
    """FC 层1 错误回填：runner 集成——参数错误以 [tool:error] 进入消息历史（不吞错）。"""
    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner

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
                     "arguments": {"content": "x"}}])  # 缺 path（故意）
            return "方案：完整执行计划"

    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = ProbeLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, BUILTIN_TOOLS(ws))
    r.run_unit("U-1", "plan", {"goal": "x"})
    # 第二轮模型必须看到参数错误（<tool_result status="error"> param: ...）
    second = " ".join(m["content"] for m in llm.seen[1]
                      if isinstance(m.get("content"), str))
    assert 'status="tool:error"' in second, \
        f"参数错误必须带状态标记回填模型：{second[-300:]!r}"
    assert "param:" in second and "path" in second
