"""TDD · L0-4：验收结论向任务状态传播——verify「结论：不通过」不得判任务 done（审查 B6）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.engine import Engine
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace

# 文本协议 helper：verify 域 require_read（读物证），execute 域 require_write（写物证）
_VERIFY_READ = "TOOLCALL:read_dependency path=out.md\n"
_EXEC_WRITE = "TOOLCALL:write_artifact path=out.md kind=result content=实现\n"


def test_verify_unpassed_unit_marked():
    """单元级：verify 输出「结论：不通过」→ 单元仍 ok（结论合法完成）但 verdict_fail 标记。"""
    class CustomLlm:
        def __init__(self): self.call_count = 0
        def name(self): return "custom"
        def chat(self, messages, tools=None):
            self.call_count += 1
            return _VERIFY_READ + "检查了产物：功能不完整。结论：不通过"
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, CustomLlm(), BUILTIN_TOOLS(ws))
    res = r.run_unit("V-1", "verify", {"goal": "验收x"})
    assert res.status == "ok", res.error
    assert getattr(res, "verdict_fail", False) is True, "不通过结论必须标记（机制裁决）"


def test_verify_passed_unit_not_marked():
    """对照：结论通过 → verdict_fail=False（不误标）。"""
    class CustomLlm:
        def name(self): return "custom"
        def chat(self, messages, tools=None):
            return _VERIFY_READ + "检查了产物：符合要求。结论：通过"
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, CustomLlm(), BUILTIN_TOOLS(ws))
    res = r.run_unit("V-2", "verify", {"goal": "验收x"})
    assert res.status == "ok"
    assert getattr(res, "verdict_fail", False) is False


_DAG_SPEC = {
    "nodes": [
        {"id": "n1", "text": "制定登录方案", "domain": {"规划": 0.9},
         "trades": [], "complexity": "high", "deliverable": "text",
         "weight": 0.5},
        {"id": "n2", "text": "实现登录功能", "domain": {"开发": 0.9},
         "trades": [], "complexity": "high", "deliverable": "text",
         "weight": 0.5},
        {"id": "n3", "text": "验证登录功能", "domain": {"验证": 0.9},
         "trades": [], "complexity": "high", "deliverable": "text",
         "weight": 0.5},
    ],
    "edges": [["n1", "n2"], ["n2", "n3"]],
}


def _eng(llm):
    """引擎 + 预置形状化（P1-2 后：complexity=high 保证 plan/execute/verify 三链不合并；
    low 时三节点并为一碎片且被 lint 重路由 execute——聚焦结论传播机制需真 verify 单元）。"""
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), llm=llm,
                 auto_confirm=True)
    eng.shape_cache.put("写一个登录功能并验收", dict(_DAG_SPEC))
    return eng


def test_task_status_propagates_unpassed():
    """任务级：verify 不通过 → 任务状态非 done（done→partial 降级），报告明示。"""
    class CustomLlm:
        def __init__(self): self.calls = 0
        def name(self): return "custom"
        def chat(self, messages, tools=None):
            self.calls += 1
            joined = " ".join(m.get("content", "") if isinstance(
                m.get("content"), str) else "" for m in messages)
            if "请验收" in joined:
                return _VERIFY_READ + "检查了产物：功能不完整。结论：不通过"
            return "方案：完整执行计划\n" + _EXEC_WRITE + "执行：实现完成"
    res = _eng(CustomLlm()).run_task("写一个登录功能并验收")
    assert res.status != "done", \
        f"verify 不通过不得判 done（实测 {res.status}）"
    assert "不通过" in res.report, "报告必须明示验收不通过"


def test_task_status_done_when_passed():
    """对照：verify 通过 → 任务 done（不误降级）。"""
    class CustomLlm:
        def __init__(self): self.calls = 0
        def name(self): return "custom"
        def chat(self, messages, tools=None):
            self.calls += 1
            joined = " ".join(m.get("content", "") if isinstance(
                m.get("content"), str) else "" for m in messages)
            if "请验收" in joined:
                return _VERIFY_READ + "检查了产物：符合要求。结论：通过"
            return "方案：完整执行计划\n" + _EXEC_WRITE + "执行：实现完成"
    res = _eng(CustomLlm()).run_task("写一个登录功能并验收")
    assert res.status == "done", res.report
