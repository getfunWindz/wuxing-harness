from wuxing.user_flow_bench import user_flow_simulate


def test_user_flow_structure():
    report = user_flow_simulate(n_variants=3, n_continuations=5)
    assert "repeat_ratio" in report   # 重复任务占比
    assert "variant_ratio" in report  # 变体占比
    assert "r3_economic_verdict" in report  # R3 经济性判断（数据驱动）
