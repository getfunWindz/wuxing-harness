"""Q11 三臂对比实验框架测试：A 机械基线 / B 静态完整 / C 自适应。"""
import pytest

from golden_ratio.calibrate import load_tasks
from golden_ratio.config import AlgorithmConfig
from golden_ratio.experiment import (
    SuccessMemory,
    adapt_bias,
    arm_config,
    cost_metric,
    granularity_deviation,
    run_experiment,
)
from golden_ratio.llm import MockLLM


def test_granularity_deviation_formula():
    assert granularity_deviation(4, 2) == pytest.approx(1.0)
    assert granularity_deviation(2, 2) == pytest.approx(0.0)
    assert granularity_deviation(1, 2) == pytest.approx(0.5)


def test_cost_metric_formula():
    # 成本 = LLM 调用 + 权重 × 跨碎片依赖边数（协调成本代理）
    assert cost_metric(llm_calls=10, cross_edges=4) == pytest.approx(12.0)
    assert cost_metric(llm_calls=10, cross_edges=4, coord_weight=1.0) == pytest.approx(14.0)


def test_arm_A_disables_synthesis_and_hierarchy():
    cfg = arm_config("A", AlgorithmConfig())
    assert (cfg.alpha, cfg.beta, cfg.gamma) == (0.0, 0.0, 0.0)
    assert cfg.hierarchical_enabled is False


def test_arm_B_keeps_calibrated_config():
    cfg = arm_config("B", AlgorithmConfig())
    assert cfg.alpha > 0 and cfg.hierarchical_enabled is True


def test_success_memory_rates():
    m = SuccessMemory()
    m.update("写作", 2, success=True)
    m.update("写作", 2, success=False)
    assert m.rate("写作", 2) == 0.5


def test_adapt_bias_low_rate_pulls_toward_zero():
    assert adapt_bias(0.2, rate=0.5, step=0.05) == pytest.approx(0.15)
    assert adapt_bias(-0.2, rate=0.5, step=0.05) == pytest.approx(-0.15)


def test_adapt_bias_clamped_to_bounds():
    v = adapt_bias(0.49, rate=0.5, step=0.05)
    assert -0.5 <= v <= 0.5
    v2 = adapt_bias(-0.49, rate=0.5, step=0.05)
    assert -0.5 <= v2 <= 0.5


def test_adapt_bias_high_rate_returns_step_half():
    # 成功率高于上限 → 回弹半步（远离 0）
    assert adapt_bias(0.2, rate=0.95, step=0.05) == pytest.approx(0.225)


def test_run_experiment_report_structure():
    tasks = load_tasks()
    report = run_experiment(tasks, MockLLM(), AlgorithmConfig(),
                            repeats=2, seed=42)
    assert {"A", "B", "C"} <= set(report["arms"])
    assert "_win_rate" in report["arms"]
    for arm in ("A", "B", "C"):
        m = report["arms"][arm]
        assert set(m) >= {"coverage", "dependency_integrity",
                          "avg_granularity_deviation", "avg_cost", "n_tasks"}
    assert report["arms"]["A"]["n_tasks"] == report["arms"]["C"]["n_tasks"]


def test_run_experiment_deterministic_with_seed():
    tasks = load_tasks()
    r1 = run_experiment(tasks, MockLLM(), AlgorithmConfig(), repeats=2, seed=7)
    r2 = run_experiment(tasks, MockLLM(), AlgorithmConfig(), repeats=2, seed=7)
    assert r1["arms"]["A"]["avg_granularity_deviation"] == \
           r2["arms"]["A"]["avg_granularity_deviation"]
    assert r1["arms"]["C"]["avg_granularity_deviation"] == \
           r2["arms"]["C"]["avg_granularity_deviation"]


def test_adaptive_runner_lowers_ratio_when_over_split():
    # C 臂新机制：over 多数 → 降低 merge_drop_ratio（更易合并）
    from golden_ratio.experiment import AdaptiveRunner
    cfg = AlgorithmConfig()
    runner = AdaptiveRunner(cfg)
    tasks = [t for t in load_tasks() if t["id"] in ("T16", "T17", "T19", "T20")]
    runner.run_warmup(tasks, MockLLM())
    assert runner.cfg.merge_drop_ratio < cfg.merge_drop_ratio
    assert runner.adaptations >= 1


def test_cost_metric_uses_cross_fragment_edges():
    # 无跨碎片依赖的碎片：协调成本为 0
    assert cost_metric(llm_calls=10, cross_edges=0) == pytest.approx(10.0)


def test_adaptive_runner_raises_ceiling_when_over_split():
    # C 臂恢复 effort_ceiling 可调：over 多数 → 上限放宽（小步长防过调）
    from golden_ratio.experiment import AdaptiveRunner
    cfg = AlgorithmConfig()
    runner = AdaptiveRunner(cfg)
    tasks = [t for t in load_tasks() if t["id"] in ("T16", "T17", "T19", "T20")]
    runner.run_warmup(tasks, MockLLM())
    assert runner.cfg.effort_ceiling > cfg.effort_ceiling


def test_ceiling_step_scales_with_task_size():
    # v3.2：ceiling 微调步长按任务规模自适应（小任务 0.01 防过调，mega 0.05 有效）
    import json

    from golden_ratio.experiment import AdaptiveRunner
    with open('golden_ratio/data/mega_tasks.json', encoding='utf-8') as f:
        mega = json.load(f)["tasks"]
    cfg = AlgorithmConfig()
    runner = AdaptiveRunner(cfg)
    runner.run_warmup([mega[0]], MockLLM())     # mega 任务总工时 > 200
    # 若 mega 任务触发 over 微调，ceiling 变化应 ≥ 0.05（大步长）
    if runner.adaptations > 0:
        assert abs(runner.cfg.effort_ceiling - 1.0) >= 0.05 - 1e-9


def test_ema_stats_forget_old_signal():
    # EMA 衰减：近期信号主导，旧信号指数遗忘（用户确认方案 1）
    from golden_ratio.experiment import ema_update
    # 连续 10 个 over 后转入 under：EMA 应快速反转方向
    stats = {"ok": 0.0, "over": 0.0, "under": 0.0}
    for _ in range(10):
        stats = ema_update(stats, "over", decay=0.9)
    assert stats["over"] > stats["under"]
    for _ in range(5):
        stats = ema_update(stats, "under", decay=0.9)
    assert stats["under"] > stats["over"], "EMA 应反映近期方向"
    # 旧信号衰减：全 over 历史后注入一个 under，over 权重应低于全量累积
    assert stats["over"] < 10.0


def test_ema_decay_reduces_old_weight():
    from golden_ratio.experiment import ema_update
    stats = {"ok": 0.0, "over": 0.0, "under": 0.0}
    stats = ema_update(stats, "over", decay=0.5)
    stats = ema_update(stats, "over", decay=0.5)
    assert stats["over"] == pytest.approx(1.5)   # 1 + 0.5×1


def test_bucket_runner_independent_buckets():
    """C 臂分桶化：不同 (领域×难度) 桶独立微调，互不污染。"""
    import json

    from golden_ratio.experiment import BucketAdaptiveRunner
    with open('golden_ratio/data/domain_tasks.json', encoding='utf-8') as f:
        dom = json.load(f)["tasks"]
    # rpg 领域全 over（需放宽），telecom 全 ok（不需调）——桶应独立响应
    rpg = [t for t in dom if t["domain_tag"] == "rpg"]
    telecom = [t for t in dom if t["domain_tag"] == "telecom"]
    cfg = AlgorithmConfig()
    runner = BucketAdaptiveRunner(cfg)
    runner.run_warmup(rpg[:5] + telecom[:5], MockLLM())
    # rpg 桶应被微调（over 方向），telecom 桶保持默认
    assert len(runner.buckets) >= 2, "应存在多个桶"
    ratios = {k: b["ratio"] for k, b in runner.buckets.items()}
    assert len(set(ratios.values())) >= 1


def test_bucket_runner_uses_bucket_params_in_test():
    """test 阶段按任务主领域×难度查桶参数。"""
    import json

    from golden_ratio.calibrate import build_dag
    from golden_ratio.experiment import BucketAdaptiveRunner
    with open('golden_ratio/data/domain_tasks.json', encoding='utf-8') as f:
        dom = json.load(f)["tasks"]
    cfg = AlgorithmConfig()
    runner = BucketAdaptiveRunner(cfg)
    runner.run_warmup(dom[:10], MockLLM())
    assert hasattr(runner, "bucket_for")
    dag = build_dag(dom[0]["dag_spec"])
    from golden_ratio.experiment import _run_task
    shape, _, _ = _run_task(dag, cfg, MockLLM())
    key = runner.bucket_for(shape)
    assert key in runner.buckets, "test 阶段应查到已建桶（主领域×难度）"


def test_arm_B_uses_m_level_ceiling():
    """B 基线收紧（v4.1）：合并上限 ≤40h（M 级健康目标，对照实验结论）。"""
    from golden_ratio.experiment import arm_config
    cfg = arm_config("B", AlgorithmConfig())
    assert cfg.m_level_cap == 40.0            # hi = min(80, T, 40) → 每块 ≤40h（绝对上限）


def test_arm_B_cap_parameterizable():
    """C 方案：cap 可参数化（cap 双标尺——T40 口径 40 / v2 口径 80）。"""
    from golden_ratio.experiment import arm_config
    cfg80 = arm_config("B", AlgorithmConfig(), cap=80.0)
    assert cfg80.m_level_cap == 80.0
    cfg40 = arm_config("B", AlgorithmConfig(), cap=40.0)
    assert cfg40.m_level_cap == 40.0


def test_run_experiment_b_cap_propagates():
    """run_experiment(b_cap=80) 应传播到 B 臂配置（C 方案实验入口）。"""
    from golden_ratio.calibrate import load_tasks
    from golden_ratio.experiment import run_experiment
    tasks = load_tasks()[:4]
    rep = run_experiment(tasks, MockLLM(), AlgorithmConfig(), repeats=1, seed=1, b_cap=80.0)
    assert "arms" in rep


def test_bucket_runner_tunes_m_level_cap():
    """C 臂微调对象更新（v4.2）：m_level_cap 参与微调——over→放宽、under→收紧。"""
    from golden_ratio.calibrate import load_tasks
    from golden_ratio.experiment import BucketAdaptiveRunner, arm_config
    cfg = arm_config("B", AlgorithmConfig())       # B 基线：cap 初始 40
    runner = BucketAdaptiveRunner(cfg)
    tasks = [t for t in load_tasks() if t["id"] in ("T16", "T17", "T19", "T20")]
    for t in tasks:
        t = dict(t)
        t["expected_fragments"] = t.get("expected_fragments_t40", t["expected_fragments"])
    runner.run_warmup(tasks, MockLLM())
    caps = {k: b["cap"] for k, b in runner.buckets.items()}
    assert all(c >= 40.0 for c in caps.values()), "over 方向应放宽 cap（≥初始 40）"


def test_bucket_runner_falls_back_to_global_direction_when_cold():
    """8.2.1 回退式：桶 seen<exp_min_adapt_samples 时用全局 EMA 方向微调该桶参数。

    构造：sports 5 个 over 任务先建立全局 over 多数，banking 桶仅 1 个任务（seen=1<2）。
    现代码 banking 桶 seen 不达标直接 continue（不微调）；回退式应使用全局方向（over）
    微调 banking 桶参数（ratio 降低）。
    """
    import json

    from golden_ratio.calibrate import build_dag
    from golden_ratio.difficulty import compute_shape
    from golden_ratio.experiment import BucketAdaptiveRunner, arm_config
    with open('golden_ratio/data/domain_tasks.json', encoding='utf-8') as f:
        dom = json.load(f)["tasks"]
    sports = [t for t in dom if t["id"] in ("S01", "S02", "S03", "S05", "S06")]  # 全 over
    banking = [t for t in dom if t["domain_tag"] == "banking"][:1]               # 冷桶
    cfg = arm_config("B", AlgorithmConfig())
    runner = BucketAdaptiveRunner(cfg)
    runner.run_warmup(sports + banking, MockLLM())
    dag = build_dag(banking[0]["dag_spec"])
    shape = compute_shape(dag, runner.cfg)
    key = runner.bucket_for(shape)
    assert key in runner.buckets
    assert runner.buckets[key]["ratio"] < cfg.merge_drop_ratio, \
        "冷桶（seen<门槛）应回退全局方向微调"


def test_bucket_runner_uses_bucket_direction_when_warm():
    """桶 seen≥门槛时仍用桶方向，即使与全局方向相反（回退逻辑不得反向破坏）。"""
    import json

    from golden_ratio.experiment import BucketAdaptiveRunner, arm_config
    cfg = arm_config("B", AlgorithmConfig())
    runner = BucketAdaptiveRunner(cfg)
    with open('golden_ratio/data/domain_tasks.json', encoding='utf-8') as f:
        dom = json.load(f)["tasks"]
    banking = [t for t in dom if t["domain_tag"] == "banking"][:5]   # 全 ok：全局 ok 多数
    sports = [t for t in dom if t["id"] in ("S01", "S02", "S03", "S05", "S06")]  # over
    runner.run_warmup(banking + sports, MockLLM())
    ratios = [b["ratio"] for b in runner.buckets.values()]
    assert any(r < cfg.merge_drop_ratio for r in ratios), \
        "warm 桶应使用桶方向（over）微调"


def test_bucket_ema_matches_module_level():
    """桶内 EMA 应与模块级 ema_update 语义一致：当前信号权重 1.0 而非 decay。"""
    import json

    from golden_ratio.calibrate import build_dag
    from golden_ratio.difficulty import compute_shape
    from golden_ratio.experiment import BucketAdaptiveRunner, ema_update
    cfg = AlgorithmConfig()
    runner = BucketAdaptiveRunner(cfg)
    with open('golden_ratio/data/domain_tasks.json', encoding='utf-8') as f:
        dom = json.load(f)["tasks"]
    # 选择一个确定 over 的任务（B微调后：S05 仍 over）
    t = next(t for t in dom if t["id"] == "S05")
    runner.run_warmup([t], MockLLM())
    dag = build_dag(t["dag_spec"])
    shape = compute_shape(dag, runner.cfg)
    key = runner.bucket_for(shape)
    b = runner.buckets[key]
    assert b["over"] == pytest.approx(1.0), "桶 EMA 首步应为 1.0（当前内联公式会得 0.9）"
    ref = ema_update({"ok": 0.0, "over": 0.0, "under": 0.0}, "over",
                     decay=cfg.exp_ema_decay)
    assert b["over"] == pytest.approx(ref["over"])


def test_hybrid_direction_weights_bucket_and_global():
    """8.2.2 融合式：方向 = w×桶 + (1−w)×全局，w = min(1, seen/5)。"""
    from golden_ratio.experiment import hybrid_direction
    g = {"ok": 0.0, "over": 2.44, "under": 1.0}   # 全局 over 多数
    b = {"ok": 0.0, "over": 0.0, "under": 10.0}   # 桶 under 强信号（seen=1）
    d = hybrid_direction(g, b, seen=1)
    # w=0.2：d_over = 0.8×2.44 + 0.2×0 = 1.952；d_under = 0.8×1.0 + 0.2×10 = 2.8
    assert d["under"] > d["over"], "桶强信号部分参与即可改变方向"
    assert d["over"] == pytest.approx(0.8 * 2.44)
    assert d["under"] == pytest.approx(0.8 * 1.0 + 0.2 * 10.0)
    # seen 达标（w=1）→ 纯桶方向
    d_warm = hybrid_direction(g, b, seen=10)
    assert d_warm["under"] == pytest.approx(10.0)
    assert d_warm["over"] == pytest.approx(0.0)
    # 无桶样本（w=0）→ 纯全局
    d_cold = hybrid_direction(g, b, seen=0)
    assert d_cold["over"] == pytest.approx(2.44)
    # w 公式：seen=2 → w=0.4
    d2 = hybrid_direction(g, b, seen=2)
    assert d2["under"] == pytest.approx(0.6 * 1.0 + 0.4 * 10.0)


def test_bucket_runner_hybrid_mode_uses_weighted_direction():
    """exp_hybrid_mode=True 时冷桶用加权方向（桶强信号按 w 参与）。"""
    from golden_ratio.experiment import BucketAdaptiveRunner, hybrid_direction
    cfg = AlgorithmConfig()
    cfg.exp_hybrid_mode = True
    runner = BucketAdaptiveRunner(cfg)
    g = {"ok": 0.0, "over": 2.44, "under": 1.0}
    b = {"ok": 0.0, "over": 0.0, "under": 10.0}
    d = runner._direction_stats(g, b, seen=1)
    ref = hybrid_direction(g, b, seen=1, scale=cfg.exp_hybrid_scale)
    assert d["under"] == pytest.approx(ref["under"])
    assert d["over"] == pytest.approx(ref["over"])
    # 回退模式（显式关闭融合）：冷桶直接取全局
    cfg2 = AlgorithmConfig()
    cfg2.exp_hybrid_mode = False
    runner2 = BucketAdaptiveRunner(cfg2)
    d2 = runner2._direction_stats(g, b, seen=1)
    assert d2["over"] == pytest.approx(2.44)
    assert d2["under"] == pytest.approx(1.0)
