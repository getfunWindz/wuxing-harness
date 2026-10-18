"""多模型评分框架（4b——用户方法论纠偏：每模型独立评分，非 A/B 对比）。"""
from wuxing.model_eval import evaluate_model


def test_eval_structure():
    report = evaluate_model(llm_spec="mock", n_tasks=2, use_real_shape=False)
    assert {"model", "n_tasks", "shape_ok", "shape_fail", "shape_compliance",
            "gran_in_interval", "gran_total", "done_rate", "status_dist",
            "unit_failed_dist", "calls", "shape_calls", "cache_reply_hit_rate"} <= set(report)
    assert 0.0 <= report["shape_compliance"] <= 1.0
    assert 0.0 <= report["done_rate"] <= 1.0
    assert "model" in report


def test_eval_deterministic_seed():
    r1 = evaluate_model(llm_spec="mock", n_tasks=3, seed=42, use_real_shape=False)
    r2 = evaluate_model(llm_spec="mock", n_tasks=3, seed=42, use_real_shape=False)
    assert r1["status_dist"] == r2["status_dist"]
