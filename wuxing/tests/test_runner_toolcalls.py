import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.tool_results import ToolCallResult
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


class ToolCallLlm:
    def __init__(self):
        self.calls = 0
    def name(self): return "tcllm"
    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return ToolCallResult(text="开始写方案", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "a.md", "kind": "plan", "content": "方案内容"}}])
        return ToolCallResult(text="方案：完整执行计划", tool_calls=[])

def test_runner_executes_tool_calls_and_returns_result():
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, ToolCallLlm(), BUILTIN_TOOLS(ws))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok"
    assert (ws.root / "a.md").exists()   # 工具执行了
    assert any("[tool]" in log or "written" in log for log in res.logs)

def test_runner_native_toolcall_blocked_by_whitelist():
    class BadCallLlm:
        def __init__(self): self.calls = 0
        def name(self): return "bad"
        def chat(self, messages, tools=None):
            self.calls += 1
            return ToolCallResult(text="x", tool_calls=[
                {"name": "bash", "arguments": {"command": "rm -rf /"}}])
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, BadCallLlm(), BUILTIN_TOOLS(ws))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    # plan 域白名单无 bash → 拦截记录
    assert "bash" in r._blocked_tools
    # LLM 死循环申请越权工具 → 停滞/安全上限护栏生效（非失控）；
    # 真测裁决 W2：基线到达后停滞 2 轮即停（不再单靠预算耗尽）
    assert res.status == "failed"
    assert "stalled" in (res.error or "") or "预算耗尽" in (res.error or "")


class TextProtoDelegateLlm:
    """文本协议（deprecated 路径）输出 delegate TOOLCALL——溯源父子链必须保留。"""

    def __init__(self):
        self.usage_history = []
        self.call_count = 0

    def name(self):
        return "textdelegate"

    def spec(self):
        return "textdelegate"

    def supports_native_tools(self):
        return False

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.usage_history.append({"input": 0, "output": 0,
                                   "cache_read": 0, "cache_write": 0})
        self.call_count += 1
        if self.call_count == 1:
            # 文本协议：TOOLCALL 行（delegate）
            return "TOOLCALL:delegate goal=制定简单方案 domain=plan\n继续执行"
        if "域：plan" in " ".join(m.get("content", "") for m in messages):
            # 子任务：产出方案（写物证）
            return ToolCallResult(text="方案：步骤1、步骤2", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "sub-text.md", "kind": "plan",
                               "content": "方案：步骤1"}}])
        return ToolCallResult(text="执行完成", tool_calls=[
            {"name": "write_artifact",
             "arguments": {"path": "main.md", "kind": "result",
                           "content": "完成"}}])


def test_text_protocol_delegate_keeps_parent_chain():
    """B6：文本协议（mock 路径）delegate 调用必须携带父单元 id——provenance 父子链不断。"""
    from wuxing.provenance import ProvenanceLedger
    from wuxing.tools.delegate import DelegateTool

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    tmp = pathlib.Path(tempfile.mkdtemp())
    ledger = ProvenanceLedger(tmp / "p.jsonl")
    cfg = EngineConfig()
    reg = DomainRegistry(cfg)
    llm = TextProtoDelegateLlm()

    def factory(goal, domain=None):
        from wuxing.runner import Runner
        sub = Runner(cfg, reg, ws, llm, BUILTIN_TOOLS(ws))
        sub._delegate_domain = domain or "plan"
        return sub, (lambda: None)

    dt = DelegateTool(factory, ledger=ledger)
    r = Runner(cfg, reg, ws, llm, BUILTIN_TOOLS(ws))
    r.tools.register(dt)
    r.run_unit("F-main", "execute", {"goal": "主任务", "task": "t",
                                     "plan": "p", "result": "",
                                     "paths": "", "fragment_key": "x"})
    rows = ledger.load()
    sub_rows = [x for x in rows if x.get("unit_id", "").startswith("delegate-")]
    assert sub_rows, f"子任务溯源记录必须存在：{rows}"
    assert sub_rows[0]["parent_id"] == "F-main", \
        f"文本协议 delegate 父链必须保留（实际 parent={sub_rows[0]['parent_id']!r}）"


def test_chat_tools_typeerror_only_falls_back_for_signature():
    """B10：_chat_with_tools 的 TypeError 回退只允许于「签名不支持 tools 参数」——
    provider 内部 TypeError（bug）不得静默降级重调（丢信息/放大故障）。"""
    import pathlib
    import tempfile

    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner as _R
    from wuxing.tools.builtin import BUILTIN_TOOLS
    from wuxing.workspace import Workspace

    calls = {"with_tools": 0, "without": 0}

    class BuggyLlm:
        def __init__(self):
            self.usage_history = []
            self.call_count = 0

        def name(self):
            return "buggy"

        def spec(self):
            return "buggy"

        def supports_native_tools(self):
            return True

        def chat(self, messages, tools=None):
            # 模拟内部 bug：tools 传入时抛 TypeError（非签名问题）
            if tools is not None:
                calls["with_tools"] += 1
                raise TypeError("internal bug: bad kwarg")
            calls["without"] += 1
            return "执行完成"

    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = BuggyLlm()
    r = _R(cfg, DomainRegistry(cfg), ws, llm, BUILTIN_TOOLS(ws))
    try:
        r.run_unit("U-x", "execute", {"goal": "g", "task": "t", "plan": "p",
                                      "result": "", "paths": "",
                                      "fragment_key": "g"})
    except TypeError:
        pass  # 内部 TypeError 应上抛（不是静默降级）
    assert calls["without"] == 0 or calls["with_tools"] == 0, \
        "内部 TypeError 不得触发降级重调（静默吞 bug）"
