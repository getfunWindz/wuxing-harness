"""TDD：#2 并行度上调（用户裁决）——默认 8、硬上限 10（Cursor 参考，机制特殊略缩）。"""
from wuxing.config import EngineConfig
from wuxing.orchestrator import MAX_PARALLEL_UNITS, Orchestrator


def test_parallel_default_is_8():
    assert EngineConfig().max_parallel_units == 8


def test_parallel_hard_cap_is_10():
    assert MAX_PARALLEL_UNITS == 10
    assert Orchestrator._parallel_limit(EngineConfig(max_parallel_units=12)) == 10
    assert Orchestrator._parallel_limit(EngineConfig(max_parallel_units=8)) == 8
    assert Orchestrator._parallel_limit(EngineConfig(max_parallel_units=0)) == 1
