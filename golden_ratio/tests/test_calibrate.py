from golden_ratio.calibrate import build_dag, calibrate, load_tasks
from golden_ratio.config import AlgorithmConfig
from golden_ratio.models import DAG


def test_suite_has_at_least_20_tasks():
    tasks = load_tasks()
    assert len(tasks) >= 20


def test_suite_covers_all_difficulty_levels():
    tasks = load_tasks()
    levels = {t["human_difficulty"] for t in tasks}
    assert levels == {1, 2, 3, 4, 5}


def test_each_task_dag_is_acyclic():
    for t in load_tasks():
        dag = build_dag(t["dag_spec"])
        assert DAG.is_acyclic(dag), f"{t['id']} 有环"


def test_calibrate_returns_report_structure():
    report = calibrate(load_tasks(), AlgorithmConfig())
    assert set(report) >= {"best_bins", "before_rate", "after_rate", "details"}
    assert len(report["best_bins"]) == 4
    b = report["best_bins"]
    assert b[0] < b[1] < b[2] < b[3]


def test_calibration_does_not_worsen():
    cfg = AlgorithmConfig()
    report = calibrate(load_tasks(), cfg)
    assert report["after_rate"] <= report["before_rate"]


def test_calibrated_misclassification_under_25pct():
    report = calibrate(load_tasks(), AlgorithmConfig())
    assert report["after_rate"] <= 0.25


def test_build_dag_rejects_dangling_edge():
    # 全面复核补漏：边引用不存在的节点必须报错（防止静默丢节点）
    import pytest

    from golden_ratio.calibrate import build_dag
    spec = {"nodes": [{"id": "n1", "text": "a", "domain": {"分析": 0.9}, "trades": ["管理"],
                       "complexity": "low", "deliverable": "decision", "weight": 0.5}],
            "edges": [["n0", "n1"]]}
    with pytest.raises(ValueError):
        build_dag(spec)
