"""TDD：P1 T2 稳定前缀布局（债 2+3——system 静态/尾部动态 + Anthropic cache_control 接线）。

知识库缓存红线：系统提示每轮变化一次 = 整条缓存失效。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.anthropic import AnthropicProvider
from wuxing.llm.tool_results import ToolCallResult
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class RoundRecorder:
    """记录每轮 messages；第一轮写物证，第二轮收敛。"""

    def __init__(self):
        self.seen = []

    def name(self):
        return "recorder"

    def chat(self, messages, tools=None):
        self.seen.append([dict(m) for m in messages])
        if len(self.seen) == 1:
            return ToolCallResult(text="我先检查依赖", tool_calls=[
                {"name": "read_dependency",
                 "arguments": {"path": "no_such.md"}}])
        return "方案：完整执行计划"


def test_system_is_static_and_user_is_dynamic():
    """域指令/工具定义必须在 system（静态）；user 只装动态参数。"""
    llm = RoundRecorder()
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    res = r.run_unit("U-1", "plan", {"goal": "写请假邮件", "task": "全任务"})
    assert res.status == "ok"
    first, second = llm.seen[0], llm.seen[1]
    sys1 = [m["content"] for m in first if m.get("role") == "system"]
    sys2 = [m["content"] for m in second if m.get("role") == "system"]
    assert sys1 == sys2, "system 消息跨轮必须逐字节稳定（缓存红线）"
    assert sys1, "system 消息必须存在"
    assert "写请假邮件" not in sys1[0], "动态 goal 不得进入 system（前缀稳定性）"
    assert "你是规划域智能体" in sys1[0], "域指令必须位于 system"
    assert "可用工具" in sys1[0], "工具定义必须位于 system（稳定前缀组成部分）"
    # user 消息：动态部分，且不再承担域指令
    user1 = " ".join(m["content"] for m in first if m.get("role") == "user")
    assert "你是规划域智能体" not in user1, "域指令不得留在 user（尾部动态）"
    assert "写请假邮件" in user1, "动态 goal 必须在 user 尾部"


class FakeResp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        pass

    def json(self):
        return self._c


def test_anthropic_system_uses_cache_control_blocks():
    """Anthropic payload.system 必须是 cache_control block 数组（债3 接线）。"""
    calls = {}

    class Http:
        def post(self, url, **kw):
            calls["body"] = kw["json"]
            return FakeResp({"content": [{"type": "text", "text": "x"}]})

    p = AnthropicProvider(api_key="k", _http=Http())
    p.chat([{"role": "system", "content": "你是助手"},
            {"role": "user", "content": "hi"}])
    system = calls["body"]["system"]
    assert isinstance(system, list), f"system 必须为 block 数组（cache_control 前提）：{system!r}"
    assert system[0]["type"] == "text"
    assert system[0]["text"] == "你是助手"
    assert system[0].get("cache_control", {}).get("type") == "ephemeral", \
        f"system 段必须打 cache_control：{system!r}"
