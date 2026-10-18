"""P15 真 LLM A/B 结构测试（真跑需 key——测试用 mock 验证结构契约）。"""
from wuxing.brain_ab import ab_compare_real


def test_ab_compare_real_structure():
    report = ab_compare_real(n_tasks=2, llm_spec="mock")
    assert {"brain_on", "brain_off", "task_list", "config"} <= set(report)
    for side in ("brain_on", "brain_off"):
        metrics = report[side]
        assert {"done_rate", "status_dist", "calls", "shape_calls",
                "failed_dist", "brain_cases"} <= set(metrics)
        # P15 缓存准则监控：命中/未命中/命中率（响应层 + 形状化层）
        assert {"reply_hits", "reply_misses", "reply_hit_rate",
                "shape_hits", "shape_misses", "shape_hit_rate"} <= set(metrics)
        # A5（2026-09-12）：观测增强——智脑选型次数 + 各模型用量（多模型证据）
        assert {"brain_picked", "model_usage"} <= set(metrics)
        assert 0.0 <= metrics["done_rate"] <= 1.0
        assert 0.0 <= metrics["reply_hit_rate"] <= 1.0
        assert 0.0 <= metrics["shape_hit_rate"] <= 1.0
    # 公平性：on 侧形状化零调用（off 先跑并复制 shape_cache）
    assert report["brain_on"]["shape_calls"] == 0
    # 记忆：收集常开（用户裁决 2026-09-06——off 侧也收集，仅决策不注入）
    assert report["brain_on"]["brain_cases"] >= 0
    assert report["brain_off"]["brain_cases"] >= 0


def test_ab_sampling_covers_suites():
    from wuxing.brain_ab import _sample_tasks
    texts = _sample_tasks(20, seed=42)
    assert len(texts) == 20
    # 抽样确定性（seed 固定 → 重复一致）
    assert _sample_tasks(20, seed=42) == texts


def test_ab_engines_disable_skill_evolution(monkeypatch):
    """第七轮审查：A/B 实验隔离——两侧引擎必须显式关闭技能自进化。

    run-2 风险：默认开时（off 侧先跑→on 侧后建 Engine）自评审可能向用户级
    skills 落盘（跨侧污染）且自评审调用不计入 calls（成本口径失真）。
    """
    import wuxing.brain_ab as ba
    seen = []

    class SpyEngine(ba.Engine):
        def __init__(self, *a, **k):
            seen.append(k.get("cfg"))
            super().__init__(*a, **k)

    monkeypatch.setattr(ba, "Engine", SpyEngine)
    ba.ab_compare_real(n_tasks=1, llm_spec="mock")
    assert len(seen) == 2, f"双侧引擎均需捕获（实际 {len(seen)}）"
    assert all(getattr(c, "skill_evolution_enabled", None) is False
               for c in seen), "A/B 两侧必须显式关闭技能自进化（实验隔离）"
