import pathlib
import tempfile

from wuxing.cache import ReplyCache
from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


class CountingLlm:
    def __init__(self): self.calls = 0
    def name(self): return "counting"
    def chat(self, messages, tools=None):
        self.calls += 1
        return "方案：完整执行计划"

def test_runner_second_run_hits_cache():
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    cache = ReplyCache(ws.root / "reply_cache.json")
    llm = CountingLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, BUILTIN_TOOLS(ws), reply_cache=cache)
    r.run_unit("U-1", "plan", {"goal": "plan:x"})
    calls_after_1 = llm.calls
    res2 = r.run_unit("U-1", "plan", {"goal": "plan:x"})  # 同域同 prompt
    assert res2.status == "ok"
    assert llm.calls == calls_after_1  # 缓存命中，LLM 无新调用
    assert cache.hits >= 1

def test_runner_cache_key_differs_by_domain():
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    cache = ReplyCache(ws.root / "reply_cache.json")
    llm = CountingLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, BUILTIN_TOOLS(ws), reply_cache=cache)
    r.run_unit("U-1", "plan", {"goal": "plan:x"})
    calls = llm.calls
    r.run_unit("U-2", "verify", {"goal": "verify:x", "result": "r"})
    assert llm.calls > calls  # 不同域 = 不同 prompt = miss（正确性：不跨域误命中）
