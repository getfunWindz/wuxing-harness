"""TDD · 会话段注入（B 模式核心：system 后/prompt 前——跨碎片逐字节一致）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.conversation import ConversationState
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class _CaptureLlm:
    def __init__(self):
        self.usage_history = []
        self.call_count = 0
        self.histories = []

    def name(self):
        return "cap"

    def spec(self):
        return "cap"

    def supports_native_tools(self):
        return False

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.usage_history.append({"input": 0, "output": 0,
                                   "cache_read": 0, "cache_write": 0})
        self.histories.append(list(messages))
        return ToolCallResult(text="执行完成", tool_calls=[
            {"name": "write_artifact", "arguments": {
                "path": "out.md", "kind": "result", "content": "x"}}])


def _state(tmp, turns=1):
    st = ConversationState(pathlib.Path(tmp) / "conv.jsonl")
    for i in range(1, turns + 1):
        st.append_turn(i, f"第{i}轮需求", [f"f{i}.py"], f"完成{i}")
    return st


def test_conversation_msg_injected_between_system_and_prompt():
    """会话段位置：system → 会话段 → prompt（前缀稳定——动态参数在最后）。"""
    tmp = tempfile.mkdtemp()
    ws = Workspace(pathlib.Path(tmp))
    cfg = EngineConfig()
    llm = _CaptureLlm()
    st = _state(tmp)
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws),
               conversation=st)
    r.run_unit("F-1", "execute", {"goal": "实现", "task": "实现任务",
                                  "plan": "步骤", "result": "", "paths": ""})
    msgs = llm.histories[0]
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user" and "[会话历史]" in msgs[1]["content"], \
        f"messages[1] 必须是会话段（实际 {msgs[1]['content'][:60]!r}）"
    assert "第1轮需求" in msgs[1]["content"]
    assert msgs[2]["role"] == "user" and "任务背景" in msgs[2]["content"], \
        "messages[2] 必须是域 prompt"


def test_conversation_segment_identical_across_fragments():
    """红线：同轮内不同碎片的会话段逐字节一致（前缀共享的前提）。"""
    tmp = tempfile.mkdtemp()
    ws = Workspace(pathlib.Path(tmp))
    cfg = EngineConfig()
    llm = _CaptureLlm()
    st = _state(tmp, turns=2)
    r1 = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws),
                conversation=st)
    r1.run_unit("F-1", "execute", {"goal": "A", "task": "T", "plan": "P",
                                   "result": "", "paths": ""})
    r2 = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws),
                conversation=st)
    r2.run_unit("F-2", "execute", {"goal": "B", "task": "T", "plan": "P",
                                   "result": "", "paths": ""})
    seg1 = llm.histories[0][1]["content"]
    seg2 = llm.histories[1][1]["content"]
    assert seg1 == seg2, "同轮内会话段必须逐字节一致（跨碎片前缀共享）"


def test_no_conversation_backward_compatible():
    """无会话参数 → messages[1] 是 prompt（向后兼容——现有 530 测试语义）。"""
    tmp = tempfile.mkdtemp()
    ws = Workspace(pathlib.Path(tmp))
    cfg = EngineConfig()
    llm = _CaptureLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    r.run_unit("F-1", "execute", {"goal": "实现", "task": "实现任务",
                                  "plan": "步骤", "result": "", "paths": ""})
    msgs = llm.histories[0]
    assert "[会话历史]" not in msgs[1]["content"]
    assert "任务背景" in msgs[1]["content"]
