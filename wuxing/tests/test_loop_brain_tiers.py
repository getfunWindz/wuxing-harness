"""TDD：智脑三级参照表（用户裁决 2026-09-06——收集常开/评判默认关/等级制度）。"""
import pathlib
import tempfile

from wuxing.engine import Engine
from wuxing.llm.brain import BrainMemory, classify_tier


def test_classify_tier_golden_ratio_band():
    """分级：成功+粒度命中 [0.382,0.618] → high；成功未命中 → normal；失败 → low。"""
    assert classify_tier(success=True, share=0.5) == "high"
    assert classify_tier(success=True, share=0.382) == "high"     # 边界含
    assert classify_tier(success=True, share=0.618) == "high"
    assert classify_tier(success=True, share=0.3) == "normal"      # 低于区间
    assert classify_tier(success=True, share=0.7) == "normal"      # 高于区间
    assert classify_tier(success=False, share=0.5) == "low"        # 完成度差


def test_tier_capacities_enforced():
    """三级容量：high/low=191 上限（黄金比 0.382×500）；超限 LRU 逐出。"""
    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json",
                      max_cases=500, high_cases=191, low_cases=191)
    for i in range(220):
        mem.record(key=f"high-{i}", domain="execute", model="m",
                   success=True, tier="high")
    highs = [c for c in mem.cases if c.get("tier") == "high"]
    assert len(highs) == 191, f"high 池必须 191 上限：{len(highs)}"
    # LRU：最早写入被逐出
    assert not any(c["key"] == "high-0" for c in mem.cases)


def test_collection_runs_when_brain_disabled():
    """收集常开：brain_enabled=False 时单元完成仍入记忆（评判默认关≠数据不收集）。"""
    import pathlib as pl
    eng = Engine(workdir=pl.Path(tempfile.mkdtemp()), auto_confirm=True)
    assert eng.brain_memory is not None, "记忆必须常建（收集常开）"
    eng.run_task("写一封请假邮件")
    assert len(eng.brain_memory.cases) >= 1, "关闭态必须收集数据（完善评判能力）"


def test_search_prefers_high_tier():
    """检索排序：高等级参照优先（同级按相似度）。"""
    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")
    mem.record(key="实现登录模块", domain="execute", model="m",
               success=True, tier="normal")
    mem.record(key="实现登录流程", domain="execute", model="m",
               success=True, tier="high")
    hits = mem.search("实现登录")
    assert hits[0]["tier"] == "high", "高等级参照必须优先"
