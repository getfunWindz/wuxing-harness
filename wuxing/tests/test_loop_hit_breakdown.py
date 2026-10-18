"""TDD：命中率细分指标（缓存问题 vs 模型能力问题的分诊仪表盘）。"""
from wuxing.reporting import build_report, compute_usage_metrics


def test_usage_metrics_cache_read_ratio():
    """服务端缓存读占比（cache_read/input——前缀缓存真实效率）。"""
    m = compute_usage_metrics({"input": 1000, "output": 200,
                               "cache_read": 600, "cache_write": 0})
    assert m["cache_read_ratio"] == 0.6


def test_usage_metrics_zero_input_safe():
    """input=0 边界（无调用/纯缓存命中场景）——不除零。"""
    m = compute_usage_metrics({"input": 0, "output": 0,
                               "cache_read": 0, "cache_write": 0})
    assert m["cache_read_ratio"] == 0.0


def test_usage_metrics_savings_estimate():
    """缓存节省估算：cache_read 按折扣价计算 vs 全价——省了多少。"""
    m = compute_usage_metrics({"input": 100000, "output": 0,
                               "cache_read": 80000, "cache_write": 0})
    # 未命中全价：20k token ×1 元/M；命中 80k×0.1 元/M——节省 = 80k×(1-0.1)
    assert m["save_tokens"] == 80000
    assert m["save_cost"] > 0


def test_report_shows_server_cache_share():
    """报告段输出「服务端缓存读占比」（人读分诊）。"""
    metrics = {"llm_calls": 3, "usage": {"input": 1000, "output": 300,
                                         "cache_read": 500, "cache_write": 0},
               "cache": {"reply": {"hits": 1, "misses": 2, "similar_hits": 0},
                         "shape": {"hits": 0, "misses": 1}}}
    r = build_report([], [], metrics)
    assert "服务端缓存读占比" in r, r
    assert "50.0%" in r or "0.5" in r, r


def test_report_shows_semantic_quality_and_failure_structure():
    """报告段输出语义命中质量 + 失效结构（误命中/毒化残留检测）。"""
    metrics = {"llm_calls": 3, "usage": {"input": 1000, "output": 300,
                                         "cache_read": 500, "cache_write": 0},
               "cache": {"reply": {"hits": 1, "misses": 2, "similar_hits": 0},
                         "shape": {"hits": 0, "misses": 1}},
               "breakdown": {"semantic_hits": 2, "semantic_ok": 2,
                              "first_round_misses": 3, "later_round_misses": 0}}
    r = build_report([], [], metrics)
    assert "语义命中质量" in r and "2 次命中" in r, r
    assert "失效结构" in r and "后续轮 miss 0" in r, r
