"""TDD：FSC 延续——保留历史 + append 新 prompt（前缀不破；session seed 不重复）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class _SeenLlm:
    def __init__(self):
        self.seen = []

    def name(self):
        return "seen"

    def chat(self, messages, tools=None):
        self.seen.append([dict(m) for m in messages])
        from wuxing.llm.tool_results import ToolCallResult
        return ToolCallResult(text="执行完成", tool_calls=[
            {"name": "write_artifact", "arguments": {
                "path": "x.md", "kind": "result", "content": "v"}}])


def test_continue_from_seeds_history_and_appends_prompt():
    cfg = EngineConfig(max_loop_rounds=4, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = _SeenLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    hist = [{"role": "system", "content": "S"},
            {"role": "user", "content": "上一轮工作历史"}]
    res = r.run_unit("U-9", "execute", {"goal": "g", "task": "t"},
                     continue_from=hist)
    assert res.status == "ok", res.error
    msgs = llm.seen[0]
    assert msgs[0]["content"] == "S", "保留历史必须作为前缀"
    assert msgs[1]["content"] == "上一轮工作历史"
    assert any("任务背景" in str(m.get("content", "")) for m in msgs[2:]), \
        "新 prompt 必须 append 在历史尾部"


def test_continue_from_does_not_mutate_source_history():
    """延续不得改写传入历史（append-only——缓存前缀不破）。"""
    cfg = EngineConfig(max_loop_rounds=4, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, _SeenLlm(), load_tools(ws))
    hist = [{"role": "system", "content": "S"},
            {"role": "user", "content": "H"}]
    r.run_unit("U-1", "execute", {"goal": "g", "task": "t"}, continue_from=hist)
    assert hist == [{"role": "system", "content": "S"},
                    {"role": "user", "content": "H"}], "原历史不得被修改"
