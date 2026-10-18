from wuxing.cache_bench import bench_scenarios


def test_bench_scenarios_structure():
    report = bench_scenarios(n_repeat=5)
    assert "repeat" in report
    assert "similar" in report
    assert "similar_drift" in report
    assert "recovery" in report
    for sc in report.values():
        assert "hit_rate" in sc
        assert "calls" in sc
        assert "calls_without_cache" in sc
