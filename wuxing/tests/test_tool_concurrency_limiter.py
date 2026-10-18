"""TDD：工具并发分级放行——软缓速/硬阻止/滞回 + 重入安全。"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from wuxing.concurrency import ToolConcurrencyLimiter, configure, get_limiter


def test_graded_release_semantics_and_hysteresis():
    lim = ToolConcurrencyLimiter(soft=2, hard=3, delay_ms=0)
    assert lim.acquire() is False   # 0 → 正常
    assert lim.acquire() is False   # 1 → 正常
    assert lim.acquire() is True    # 2 → 缓速档
    # active=3 = hard → 阻止
    gate = threading.Event()

    def worker():
        lim.acquire()
        gate.set()
        lim.release()

    t = threading.Thread(target=worker)
    t.start()
    assert not gate.wait(0.2), "达到硬上限必须阻止放行"
    lim.release()                   # 回落 → 仍缓速档（2）→ 放行
    assert gate.wait(2), "释放后必须放行"
    t.join()
    lim.release()
    lim.release()                   # 回落到 0
    assert lim.acquire() is False, "回落软阈值下必须恢复正常放行"
    lim.release()


def test_registry_enforces_graded_release():
    """集成：6 并发调用 + hard=2 → 恰好 2 并发（Barrier(2) 确定性证据）。"""
    from wuxing.protocols import Tool, ToolResult
    from wuxing.tools.base import ToolRegistry

    state = {"lock": threading.Lock(), "active": 0, "max": 0}
    barrier = threading.Barrier(2)  # 必须有两个调用同时在跑才放行

    class Probe(Tool):
        reentrant = False

        def name(self):
            return "probe"

        def description(self):
            return "p"

        def input_schema(self):
            return {"type": "object", "properties": {}}

        def permission(self):
            return {"read": True, "write": False, "execute": False,
                    "network": False, "destructive": False}

        def execute(self, **kw):
            with state["lock"]:
                state["active"] += 1
                state["max"] = max(state["max"], state["active"])
            try:
                barrier.wait(timeout=3)  # 上限若失效（>2）或过严（<2）都会失败
                time.sleep(0.01)
            finally:
                with state["lock"]:
                    state["active"] -= 1
            return ToolResult(status="ok", content="ok")

    configure(soft=1, hard=2, delay_ms=0)
    try:
        reg = ToolRegistry([Probe()])
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = [ex.submit(reg.execute, "probe") for _ in range(6)]
            for f in futs:
                assert f.result().status == "ok"
        assert state["max"] == 2, f"必须恰好 2 并发（实际 {state['max']}）"
    finally:
        configure(soft=64, hard=100, delay_ms=25)


def test_reentrant_tool_bypasses_limiter():
    """重入工具（delegate 类）不占额度——硬上限满时仍可执行（防死锁）。"""
    from wuxing.protocols import Tool, ToolResult
    from wuxing.tools.base import ToolRegistry

    class Re(Tool):
        reentrant = True

        def name(self):
            return "re"

        def description(self):
            return "r"

        def input_schema(self):
            return {"type": "object", "properties": {}}

        def permission(self):
            return {"read": True, "write": False, "execute": False,
                    "network": False, "destructive": False}

        def execute(self, **kw):
            return ToolResult(status="ok", content="ok")

    configure(soft=1, hard=1, delay_ms=0)
    lim = get_limiter()
    lim.acquire()  # 额度占满（hard=1）
    try:
        reg = ToolRegistry([Re()])
        done = threading.Event()
        res = {}

        def call():
            res["out"] = reg.execute("re")
            done.set()

        t = threading.Thread(target=call)
        t.start()
        assert done.wait(2), "重入工具不得被额度阻塞（防死锁）"
        assert res["out"].status == "ok"
        t.join()
    finally:
        lim.release()
        configure(soft=64, hard=100, delay_ms=25)
