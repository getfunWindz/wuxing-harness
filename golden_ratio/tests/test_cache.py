"""输出缓存测试（LLM接入降成本方案 #1：相同/相似任务文本的 DAG 输出缓存）。"""
from golden_ratio.cache import CachedLLM
from golden_ratio.llm import MockLLM


def test_cache_hit_skips_inner_call():
    inner = MockLLM()
    cached = CachedLLM(inner)
    r1 = cached.shape_task("写一封请假邮件")
    n_after_first = inner.call_count
    r2 = cached.shape_task("写一封请假邮件")
    assert inner.call_count == n_after_first, "命中缓存时不应调用内层"
    assert r1 == r2


def test_cache_key_normalizes_whitespace_and_case():
    inner = MockLLM()
    cached = CachedLLM(inner)
    cached.shape_task("  写一封请假邮件  ")
    cached.shape_task("写一封请假邮件")
    assert inner.call_count == 1, "空白归一后应命中"


def test_cache_key_lowercases_english():
    inner = MockLLM()
    cached = CachedLLM(inner)
    cached.shape_task("Build a User System")
    cached.shape_task("build a user system")
    assert inner.call_count == 1, "英文大小写归一后应命中"


def test_cache_misses_for_different_tasks():
    inner = MockLLM()
    cached = CachedLLM(inner)
    cached.shape_task("写一封请假邮件")
    cached.shape_task("写一份季度报告")
    assert inner.call_count == 2
    assert cached.hits == 0 and cached.misses == 2


def test_cache_counts_hits():
    inner = MockLLM()
    cached = CachedLLM(inner)
    cached.shape_task("写一封请假邮件")
    cached.shape_task("写一封请假邮件")
    cached.shape_task("写一封请假邮件")
    assert cached.hits == 2
    assert cached.misses == 1


def test_cache_returns_deepcopy_not_reference():
    inner = MockLLM()
    cached = CachedLLM(inner)
    out = cached.shape_task("写一封请假邮件")
    out["nodes"][0]["text"] = "被篡改"
    again = cached.shape_task("写一封请假邮件")
    assert again["nodes"][0]["text"] != "被篡改", "缓存应返回深拷贝"


def test_cache_delegates_other_methods():
    inner = MockLLM()
    cached = CachedLLM(inner)
    m = cached.merge_nodes([{"id": "n1"}])
    assert m == [["n1"]]
    assert cached.rebalance_suggest({"x": 1}) == {"moves": []}
    assert cached.score_keys(["a", "b"]) == {"a": 1.0, "b": 0.5}


def test_cache_capacity_evicts_oldest():
    inner = MockLLM()
    cached = CachedLLM(inner, max_entries=2)
    for t in ("任务1", "任务2", "任务3"):
        cached.shape_task(t)
    cached.shape_task("任务1")     # 任务1 已被逐出 → 应重新调用内层
    assert inner.call_count >= 4
