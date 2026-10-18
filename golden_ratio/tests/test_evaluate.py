from golden_ratio.evaluate import TASK_SUITE, evaluate
from golden_ratio.llm import MockLLM


def test_task_suite_has_four_tasks():
    assert len(TASK_SUITE) == 4


def test_evaluate_returns_all_metrics():
    llm = MockLLM()
    report = evaluate(llm)
    assert report["coverage"] == 1.0
    assert report["dependency_integrity"] == 1.0
    assert report["llm_calls"] >= 4
    assert 0.0 <= report["avg_fragments"] <= 10.0


def test_evaluate_stability_with_noise_is_high_for_mock():
    llm = MockLLM()
    r1 = evaluate(llm)
    r2 = evaluate(llm)
    assert r1["stability"] == 1.0
    assert r2["stability"] == 1.0
