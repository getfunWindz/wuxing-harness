"""TDD：P1 T4 命中率/成本指标暴露（债 4 收尾——用户底线可验证的度量口径）。"""
import pathlib

from wuxing.engine import Engine


def test_task_metrics_in_result():
    """run_task 后 TaskResult.metrics 含 llm_calls/cache 统计（报告可引用）。"""
    eng = Engine(workdir=pathlib.Path(__import__("tempfile").mkdtemp()))
    res = eng.run_task("写一封请假邮件")
    m = res.metrics
    assert "llm_calls" in m and m["llm_calls"] >= 1, m
    assert "cache" in m, m
    assert "reply" in m["cache"] and "shape" in m["cache"], m
    assert "usage" in m, m
    # 首次运行：全部 miss（无预置缓存）
    assert m["cache"]["reply"]["misses"] >= 1, m
    assert m["cache"]["shape"]["misses"] >= 1, m


def test_second_run_cache_hits_reflected():
    """同任务二跑：shape 命中且 reply 命中（基线量化的机械验证）。

    机制测试固定 mock 形状化路径：真实形状化默认开且无凭据时降级结果不写缓存
    （配好凭据后可重跑真实形状化）——会遮蔽本测试的缓存命中意图（2026-09-18）。
    """
    from wuxing.config import EngineConfig
    wd = pathlib.Path(__import__("tempfile").mkdtemp())
    e1 = Engine(cfg=EngineConfig(use_real_shape=False), workdir=wd,
                auto_confirm=True)
    e1.run_task("写一封请假邮件")
    e2 = Engine(cfg=EngineConfig(use_real_shape=False), workdir=wd,
                auto_confirm=True)
    res = e2.run_task("写一封请假邮件")
    m = res.metrics["cache"]
    assert m["shape"]["hits"] >= 1, m
    assert m["reply"]["hits"] >= 1, m


def test_report_contains_cache_metrics():
    """任务报告文本必须包含缓存统计段（人类可读的度量输出）。"""
    eng = Engine(workdir=pathlib.Path(__import__("tempfile").mkdtemp()))
    res = eng.run_task("写一封请假邮件")
    assert "LLM 调用" in res.report, res.report
    assert "回复缓存" in res.report, res.report
