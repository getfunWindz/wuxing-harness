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


def test_concurrent_same_prompt_calls_llm_once():
    """I1（v65）：两个 Runner 共享 ReplyCache 并发同 prompt → 只调一次 LLM。"""
    import threading
    import time

    cfg = EngineConfig()
    cache = ReplyCache(pathlib.Path(tempfile.mkdtemp()) / "reply_cache.json")
    workspace_a = Workspace(pathlib.Path(tempfile.mkdtemp()))
    workspace_b = Workspace(pathlib.Path(tempfile.mkdtemp()))

    class SlowCountingLlm:
        def __init__(self):
            self.calls = 0
            self.entered = threading.Event()
            self.release = threading.Event()

        def name(self): return "slow-counting"

        def chat(self, messages, tools=None):
            self.calls += 1
            self.entered.set()
            self.release.wait(timeout=5)
            return "方案：并发单飞"

    llm = SlowCountingLlm()
    runner_a = Runner(cfg, DomainRegistry(cfg), workspace_a, llm,
                      BUILTIN_TOOLS(workspace_a), reply_cache=cache)
    runner_b = Runner(cfg, DomainRegistry(cfg), workspace_b, llm,
                      BUILTIN_TOOLS(workspace_b), reply_cache=cache)
    results = []

    t1 = threading.Thread(
        target=lambda: results.append(runner_a.run_unit("U-1", "plan", {"goal": "plan:x"})))
    t1.start()
    assert llm.entered.wait(timeout=2)
    t2 = threading.Thread(
        target=lambda: results.append(runner_b.run_unit("U-1", "plan", {"goal": "plan:x"})))
    t2.start()
    deadline = time.time() + 2
    while cache.singleflight_waits < 1 and time.time() < deadline:
        time.sleep(0.01)
    llm.release.set()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert not t1.is_alive() and not t2.is_alive()
    assert llm.calls == 1, f"并发同 prompt 只应调用一次 LLM（实际 {llm.calls}）"
    assert len(results) == 2 and all(r.status == "ok" for r in results)
