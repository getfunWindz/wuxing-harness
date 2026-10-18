"""E2-5 排期池 A1：`todo_write` 单元内任务清单（整表替换 / 校验 / 非判定 / 隔离）。

计划：docs/plans/2026-10-03-wuxing-todo-list.md（T1-T3）。
纪律：清单=模型侧自查工具——**非判定**（完成仍以物证+verify 为准）、单所有者、
整表替换（无部分更新）、单元开始清空。
"""

import pathlib

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.runner_support import _NO_SIDE_EFFECT, _is_side_effect_free
from wuxing.tools.base import ToolRegistry
from wuxing.tools.todo_tool import MAX_TODO_ITEM_CHARS, MAX_TODO_ITEMS, TodoWriteTool
from wuxing.trace import TraceLogger
from wuxing.workspace import Workspace

# ---------------- T1：工具与校验 ----------------

def test_whole_table_replace():
    """第二次调用全量替换第一次（无合并/无部分更新）。"""
    t = TodoWriteTool()
    r1 = t.execute(items=[{"content": "第一步", "status": "pending"},
                          {"content": "第二步", "status": "pending"}])
    assert r1.status == "ok"
    r2 = t.execute(items=[{"content": "只剩一条", "status": "in_progress"}])
    assert r2.status == "ok"
    assert [i["content"] for i in t.items] == ["只剩一条"]
    assert [i["status"] for i in t.items] == ["in_progress"]


def test_invalid_status_rejected_loud():
    """status 非法 → error，指明条目序号；状态不变（loud 校验）。"""
    t = TodoWriteTool()
    t.execute(items=[{"content": "a", "status": "pending"}])
    before = [dict(i) for i in t.items]
    r = t.execute(items=[{"content": "a", "status": "pending"},
                         {"content": "b", "status": "bogus"}])
    assert r.status == "error"
    assert "items[1]" in r.error, f"必须指明违规条目序号：{r.error}"
    assert "pending" in r.error and "in_progress" in r.error, \
        f"必须列明合法状态集：{r.error}"
    assert t.items == before, "校验失败不得改动状态"


def test_item_count_and_length_limits():
    """条目 >20 或 content >200 字符 → error（loud）。"""
    t = TodoWriteTool()
    many = [{"content": f"x{i}", "status": "pending"}
            for i in range(MAX_TODO_ITEMS + 1)]
    r = t.execute(items=many)
    assert r.status == "error" and str(MAX_TODO_ITEMS) in r.error
    long_content = "长" * (MAX_TODO_ITEM_CHARS + 1)
    r2 = t.execute(items=[{"content": long_content, "status": "pending"}])
    assert r2.status == "error" and str(MAX_TODO_ITEM_CHARS) in r2.error


def test_permission_declaration_and_serial_semantics():
    """permission: read=True，其余全假；不进 `_NO_SIDE_EFFECT` 免并发表——
    整表替换需保序：走顺序语义（不得与其它调用并发批）。"""
    t = TodoWriteTool()
    assert t.permission() == {"read": True, "write": False, "execute": False,
                              "network": False, "destructive": False}
    assert "todo_write" not in _NO_SIDE_EFFECT
    reg = ToolRegistry([t])
    assert _is_side_effect_free("todo_write", reg) is False, \
        "todo_write 必须串行（整表替换保序）"


def test_schema_and_description():
    """入参 schema 声明 items；描述含纪律文案（整表替换/非判定）。"""
    t = TodoWriteTool()
    schema = t.input_schema()
    assert "items" in schema.get("properties", {})
    assert "items" in schema.get("required", [])
    desc = t.description()
    assert "整表" in desc and "不" in desc  # 含「非判定」语义提示


# ---------------- T2：状态与 trace（run 作用域 + 单元清空） ----------------

def _runner(tmp_path, trace=None):
    """轻量 Runner：真实工具/注册表 + 哑 LLM（只验证生命周期与观测面）。"""
    class _NullLlm:
        def name(self):
            return "null"

    root = pathlib.Path(tmp_path)
    root.mkdir(parents=True, exist_ok=True)
    cfg = EngineConfig()
    ws = Workspace(root)
    tool = TodoWriteTool()
    r = Runner(cfg, DomainRegistry(cfg), ws, _NullLlm(), [tool], trace=trace)
    r._current_domain_id = "execute"
    r._messages = []
    return r, ws, tool


def test_state_cleared_at_unit_start(tmp_path):
    """单元 A 写表后，单元 B 起始为空（不串表）。"""
    r, _ws, tool = _runner(tmp_path)
    r.tools.execute("todo_write",
                    items=[{"content": "a", "status": "pending"}])
    assert tool.items, "前置：清单已写入"
    r._init_unit_runtime("U-1", "execute", {"goal": "g"}, r.llm, None, None)
    assert tool.items == [], "单元开始必须清空清单（防跨单元串表）"


def test_trace_snapshot_append_only(tmp_path):
    """每次 todo_write → trace 事件含全量快照；旧事件不改（append-only）。"""
    trace_path = pathlib.Path(tmp_path) / ".wuxing" / "trace.jsonl"
    trace = TraceLogger(trace_path)
    r, _ws, tool = _runner(tmp_path, trace=trace)
    r._init_unit_runtime("U-1", "execute", {"goal": "g"}, r.llm, None, None)
    r._execute_toolcall(
        {"name": "todo_write",
         "arguments": {"items": [{"content": "a", "status": "pending"}]}},
        [tool], "U-1")
    r._execute_toolcall(
        {"name": "todo_write",
         "arguments": {"items": [{"content": "a", "status": "in_progress"},
                                 {"content": "b", "status": "pending"}]}},
        [tool], "U-1")
    rows = trace.load()
    snapshots = [x for x in rows if x.get("event") == "todo_write"]
    assert len(snapshots) == 2, f"每次写表必须落一条快照：{rows}"
    assert snapshots[0]["items"] == [{"content": "a", "status": "pending"}]
    assert snapshots[1]["items"][1] == {"content": "b", "status": "pending"}
    assert snapshots[1]["unit_id"] == "U-1"


def test_parallel_fragments_isolated(tmp_path):
    """两 run 并行（per-run 引擎）互不可见对方 todo。"""
    r1, _ws1, t1 = _runner(tmp_path / "r1")
    _r2, _ws2, t2 = _runner(tmp_path / "r2")
    r1.tools.execute("todo_write",
                     items=[{"content": "a", "status": "pending"}])
    assert t1.items and t2.items == []
    _r2.tools.execute("todo_write",
                      items=[{"content": "b", "status": "pending"}])
    assert t1.items[0]["content"] == "a"
    assert t2.items[0]["content"] == "b"


# ---------------- T3：白名单与提示词集成（plan/execute） ----------------

def test_whitelist_plan_execute_only():
    """plan/execute 可达；design/verify/user 不可达。"""
    from wuxing.domains.defaults import DEFAULT_DOMAINS, DESIGN_DOMAIN
    assert "todo_write" in DEFAULT_DOMAINS["plan"].tool_whitelist
    assert "todo_write" in DEFAULT_DOMAINS["execute"].tool_whitelist
    assert "todo_write" not in DEFAULT_DOMAINS["verify"].tool_whitelist
    assert "todo_write" not in DEFAULT_DOMAINS["user"].tool_whitelist
    assert "todo_write" not in DESIGN_DOMAIN.tool_whitelist


def test_loader_registers_todo(tmp_path):
    """统一装载器含 todo_write（内置面）。"""
    from wuxing.tools.loader import load_tools
    ws = Workspace(pathlib.Path(tmp_path))
    reg = load_tools(ws)
    tool = reg.get("todo_write")
    assert tool is not None and tool.name() == "todo_write"


class _TodoOnlyLlm:
    """首轮写「全部完成」清单 + 后续完成文案——但无写物证（非判定性回归）。"""

    def __init__(self):
        self.calls = 0

    def name(self):
        return "todo-only"

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.calls += 1
        if self.calls == 1:
            return ToolCallResult(text="", tool_calls=[
                {"name": "todo_write",
                 "arguments": {"items": [
                     {"content": "步骤一", "status": "completed"},
                     {"content": "步骤二", "status": "completed"}]}}])
        return "完成 done（清单全部 completed）"


def test_todo_not_gating_completion(tmp_path):
    """带 todo_write 的单元：完成判定仍只看物证/契约（不因清单全完成而 ok）。"""
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2)
    ws = Workspace(pathlib.Path(tmp_path))
    tool = TodoWriteTool()
    r = Runner(cfg, DomainRegistry(cfg), ws, _TodoOnlyLlm(), [tool])
    res = r.run_unit("U-1", "execute", {"goal": "g"})
    assert res.status == "failed", f"清单不是判定依据：{res.status}"
