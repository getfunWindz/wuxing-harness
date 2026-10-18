"""预算护栏测试（LLM接入降成本方案 #7：每任务调用预算，超限抛错回退）。"""
import pytest

from golden_ratio.guard import BudgetExceeded, BudgetGuard
from golden_ratio.llm import MockLLM


def test_guard_allows_within_budget():
    g = BudgetGuard(MockLLM(), max_calls=3)
    g.shape_task("写一封请假邮件")
    assert g.calls == 1


def test_guard_raises_when_exceeded():
    g = BudgetGuard(MockLLM(), max_calls=2)
    g.shape_task("t1")
    g.shape_task("t2")
    with pytest.raises(BudgetExceeded):
        g.shape_task("t3")


def test_guard_reset():
    g = BudgetGuard(MockLLM(), max_calls=1)
    g.shape_task("t1")
    with pytest.raises(BudgetExceeded):
        g.shape_task("t2")
    g.reset()
    g.shape_task("t3")          # 复位后恢复
    assert g.calls == 1


def test_guard_delegates_other_methods():
    g = BudgetGuard(MockLLM())
    assert g.merge_nodes([{"id": "n1"}]) == [["n1"]]
    assert g.rebalance_suggest({}) == {"moves": []}
    assert g.score_keys(["a"]) == {"a": 1.0}


def test_cached_guard_combination_cache_hit_not_counted():
    """组合：CachedLLM(BudgetGuard(inner))——缓存命中不消耗预算（预算=真实API调用）。"""
    from golden_ratio.cache import CachedLLM
    inner = MockLLM()
    guard = BudgetGuard(inner, max_calls=1)
    cached = CachedLLM(guard)
    cached.shape_task("写一封请假邮件")          # miss → 预算 1
    cached.shape_task("写一封请假邮件")          # hit → 预算不变
    assert guard.calls == 1
    with pytest.raises(BudgetExceeded):
        cached.shape_task("另一个任务")          # miss → 超预算
