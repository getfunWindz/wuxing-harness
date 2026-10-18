"""TDD · L4/GLM 差分：plan 碎片隐式全局前置 + bash Windows 语法提示。"""
import pathlib
import tempfile

from wuxing.engine import Engine
from wuxing.workspace import Workspace


class OrderLlm:
    """记录调用顺序（plan 先于 execute——计划全局前置验证）。"""

    def __init__(self):
        self.order = []

    def name(self):
        return "order"

    def chat(self, messages, tools=None):
        joined = " ".join(str(m.get("content", "")) for m in messages)
        if "制定方案" in joined or "请为任务制定" in joined:
            self.order.append("plan")
            return ("方案：完整计划\n"
                    "TOOLCALL:write_artifact path=plan.md kind=plan content=方案")
        self.order.append("execute")
        return ("执行完成\n"
                "TOOLCALL:write_artifact path=out.md kind=result content=结果")


def test_plan_fragment_runs_first():
    """plan 碎片必须先于 execute 碎片（并行调度修复——计划是全球前置依赖）。"""
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), llm=OrderLlm(),
                 auto_confirm=True)
    eng.shape_cache.put("实现并验证", {
        "nodes": [
            {"id": "n1", "text": "制定实现方案", "domain": {"规划": 0.9},
             "trades": [], "complexity": "low", "deliverable": "text",
             "weight": 0.5},
            {"id": "n2", "text": "实现功能", "domain": {"开发": 0.9},
             "trades": [], "complexity": "low", "deliverable": "code",
             "weight": 0.5}],
        "edges": [["n1", "n2"]]})
    res = eng.run_task("实现并验证")
    llm = eng.llm
    assert llm.order[0] == "plan", f"plan 必须先执行：{llm.order}"
    assert res.status in ("done", "partial"), res.report


def test_bash_desc_unix_tools_hint():
    """bash 工具描述声明 Unix 风格命令可用（Wave-1 B3 改口）——PATH 注入后
    ls/cat/grep/rg 等可直接使用；不再用「勿用」误导模型。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    from wuxing.tools.bash_tool import BashTool
    d = BashTool(ws).description()
    assert "grep" in d and "勿用" not in d, "描述须声明 Unix 工具可用"
