"""TDD · C-2：消息组装重排——任务共同上下文前置（跨碎片共享前缀=服务端缓存复用）。

知识库「缓存复用从开头匹配——第 N 个 token 变了前缀到 N 为止」：
同任务碎片的 user 消息须共享【任务背景+计划注入】前缀；碎片特有（goal/交付物）
在尾部——首轮即命中（66%→90/95 的结构路径）。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


class _RecLlm:
    def __init__(self):
        self.seen = []

    def name(self):
        return "rec"

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.seen.append([dict(m) for m in messages])
        joined = " ".join(str(m.get("content", "")) for m in messages)
        if "制定方案" in joined or "请为任务制定" in joined:
            return ToolCallResult(text="", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "p.md", "kind": "plan", "content": "方案x"}}])
        return ToolCallResult(text="", tool_calls=[
            {"name": "read_dependency", "arguments": {"path": "no.md"}}])


def _run_pair():
    """同任务两碎片（plan + execute）——对比首轮 user 消息共同前缀。"""
    cfg = EngineConfig(max_loop_rounds=4, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = _RecLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, BUILTIN_TOOLS(ws))
    task = "开发一个用户系统"
    r.run_unit("P-1", "plan", {"goal": "制定开发方案", "task": task,
                               "plan": "", "result": "", "paths": ""})
    r.run_unit("E-1", "execute", {"goal": "实现登录功能", "task": task,
                                  "plan": "方案文本A", "result": "", "paths": ""})
    return llm


def test_task_context_precedes_fragment_goal():
    """任务背景必须位于碎片目标之前（变异点后推——共享前缀最大化）。"""
    llm = _run_pair()
    plan_user = next(m for m in llm.seen[0] if m.get("role") == "user")["content"]
    next(m["content"] for m in llm.seen[1] if m.get("role") == "user")
    i_plan = plan_user.find("制定开发方案")
    i_task = plan_user.find("开发一个用户系统")
    assert i_task != -1 and i_plan != -1 and i_task < i_plan, \
        f"任务背景必须先于碎片目标：{plan_user[:120]!r}"


def test_shared_prefix_across_fragments():
    """同任务碎片首轮 user 消息：任务背景段完全相同（跨碎片前缀共享）。"""
    llm = _run_pair()
    plan_user = next(m for m in llm.seen[0] if m.get("role") == "user")["content"]
    exec_user = next(m["content"] for m in llm.seen[1] if m.get("role") == "user")
    # 共同前缀 = 任务背景段（长度为 task 文本 + 模板头）——两碎片必须一致
    common = 0
    for a, b in zip(plan_user, exec_user):
        if a != b:
            break
        common += 1
    assert common >= len("任务背景：开发一个用户系统") - 2, \
        f"共享前缀过短（{common}）——跨碎片缓存复用受损：{plan_user[:100]!r} / {exec_user[:100]!r}"


def test_system_shared_header_across_domains():
    """C-2.5：system 公共头前置——安全/收敛/行动段跨域逐字相同（跨域前缀共享）。

    域差异段（头衔/质量注记/工具表）在尾部——跨碎片（不同域）共享 system 前缀。
    """
    cfg = EngineConfig(max_loop_rounds=4, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = _RecLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, BUILTIN_TOOLS(ws))
    task = "开发一个用户系统"
    r.run_unit("P-1", "plan", {"goal": "制定方案", "task": task,
                               "plan": "", "result": "", "paths": ""})
    r.run_unit("V-1", "verify", {"goal": "验证", "task": task,
                                 "plan": "", "result": "结果", "paths": "p.md"})
    plan_sys = next(m for m in llm.seen[0] if m.get("role") == "system")["content"]
    ver_sys = next(m for m in llm.seen[1] if m.get("role") == "system")["content"]
    common = 0
    for a, b in zip(plan_sys, ver_sys):
        if a != b:
            break
        common += 1
    assert common >= 100, \
        f"system 公共头过短（{common}）——跨域碎片前缀无共享：{plan_sys[:120]!r}"
