from wuxing.llm.mock import MockLlmProvider


def test_mock_chat_deterministic():
    llm = MockLlmProvider()
    r1 = llm.chat([{"role": "user", "content": "为写一篇请假邮件制定方案"}])
    r2 = llm.chat([{"role": "user", "content": "为写一篇请假邮件制定方案"}])
    assert r1 == r2
    assert llm.call_count == 2

def test_mock_returns_plan_content():
    llm = MockLlmProvider()
    out = llm.chat([{"role": "user", "content": "plan:写一篇请假邮件"}])
    # P0 T3：mock 返回 ToolCallResult（带写产物物证——域契约硬化后纯文本不再通过）
    assert "方案" in out.text
    assert out.tool_calls and out.tool_calls[0]["name"] == "write_artifact"


def test_thread_usage_segments_isolated():
    """B12：并发共享 llm 时 usage 统计必须按线程隔离——thread-local 段精确
    （此前共享 list 快照差分：并发碎片把对方调用计入自己——指标失真）。"""
    import threading

    from wuxing.llm.base import BaseLlmProvider

    class P(BaseLlmProvider):
        def __init__(self):
            super().__init__(max_retries=0)

        def name(self):
            return "p"

        def chat(self, messages, tools=None):
            self._record_usage({"input": 10, "output": 5,
                                "cache_read": 0, "cache_write": 0})
            return "x"

    p = P()
    barrier = threading.Barrier(2)
    out = {}

    def worker(tag):
        barrier.wait()
        snap = p._usage_snapshot()
        p.chat([])
        p.chat([])  # 两次调用
        seg = p._take_usage_since(snap)
        out[tag] = seg

    ts = [threading.Thread(target=worker, args=(t,)) for t in ("a", "b")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(out["a"]) == 2, f"a 线程必须拿到自己的 2 次调用（实际 {len(out['a'])}）"
    assert len(out["b"]) == 2, f"b 线程必须拿到自己的 2 次调用（实际 {len(out['b'])}）"
    for tag in ("a", "b"):
        for u in out[tag]:
            assert u["input"] == 10, f"{tag} 线程 usage 不得串入他人记录"
