"""TDD · M1-2：碎片上下文投影——任务背景确定性截断（CC「投影→压缩→缓存→恢复」）。

问题（n=5 归因）：execute 碎片探索不止——碎片 prompt 携带完整大任务背景（数百
token）淹没碎片目标。投影：task 段截断（同任务确定性——跨碎片一致=前缀共享保持）。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


class _Rec:
    def __init__(self):
        self.seen = []

    def name(self):
        return "rec"

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.seen.append([dict(m) for m in messages])
        return ToolCallResult(text="", tool_calls=[
            {"name": "write_artifact",
             "arguments": {"path": "p.md", "kind": "result", "content": "x"}}])


def test_task_background_projected_and_deterministic():
    """长任务背景投影（截断超阈值）——确定性（同任务两次结果一致）。"""
    from wuxing.context import project_task_context
    long_task = "开发企业级用户系统" + ("，包含登录注册/权限管理/订单流程/支付集成" * 30)
    a = project_task_context(long_task, max_chars=300)
    b = project_task_context(long_task, max_chars=300)
    assert a == b, "投影必须确定性（同输入同结果——缓存前缀稳定）"
    assert len(a) <= 300 + 60, f"投影后超限（含尾注）：{len(a)}"
    assert a.startswith(long_task[:300]), "保留开头（前缀共享——跨碎片一致性）"
    assert a != long_task, "超限任务必须被投影"


def test_short_task_untouched():
    """未超限任务零改动（零扰动——与缓存键稳定一致）。"""
    from wuxing.context import project_task_context
    t = "写一封请假邮件"
    assert project_task_context(t) == t


def test_projected_context_in_prompt():
    """runner prompt 注入投影后 task（碎片目标聚焦——探索不止缓解）。"""
    from wuxing.context import project_task_context
    cfg = EngineConfig(max_loop_rounds=4, max_unit_budget=3,
                       task_context_max_chars=200)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = _Rec()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, BUILTIN_TOOLS(ws))
    long_task = "开发企业级用户系统" + ("，包含登录注册/权限管理/订单/支付" * 25)
    r.run_unit("E-1", "execute", {"goal": "实现登录", "task": long_task,
                                  "plan": "", "result": "", "paths": ""})
    usr = next(m for m in llm.seen[0] if m.get("role") == "user")["content"]
    expect = project_task_context(long_task, max_chars=200)
    assert expect in usr, "prompt 必须使用投影后任务上下文"
    assert len(long_task) > len(expect)  # 确实被投影
