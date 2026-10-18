"""校准 anti-collapse 正则测试（优化方向 2）：防"最优 bins"档位塌缩。

背景（阶段3 发现）：网格搜索以"最小错误率"为目标时，112bins 最优解把 b1 拉到 5.04
→ L2 区间吞掉语义 L3/L4 任务（T12/P03/T18 挤进快路径）——错误率最小不代表语义
可解释。修复：校准目标 = 错误率 + λ·塌缩惩罚（档位分布与均衡分布的偏离）。
"""
import json

from golden_ratio.calibrate import (
    _predict,
    build_dag,
    calibrate_with_regularization,
    collapse_penalty,
)
from golden_ratio.config import AlgorithmConfig
from golden_ratio.difficulty import compute_shape


def _pairs_demo():
    """构造 ds 密集集中在 5.0 附近的模拟样本（T12 类塌缩场景）。"""
    return [(4.9, 2), (5.0, 3), (5.1, 4), (5.2, 4), (5.0, 3), (4.8, 2), (5.3, 5), (5.1, 4)]


def test_collapse_penalty_zero_for_even_distribution():
    """五档均分 → 惩罚 0。"""
    bins = (1.0, 2.0, 3.0, 4.0)
    pairs = [(d, (i % 5) + 1) for i, d in enumerate([0.5, 1.5, 2.5, 3.5, 4.5])]
    p = collapse_penalty(pairs, bins)
    assert p == 0.0


def test_collapse_penalty_positive_for_collapsed_bins():
    """档位塌缩（全部样本进 L2）→ 惩罚 > 0。"""
    bins = (5.0, 5.02, 5.03, 5.04)
    pairs = [(5.01, 3), (5.005, 3), (5.015, 3), (5.02, 3)]
    p = collapse_penalty(pairs, bins)
    assert p > 0.0


def test_collapse_penalty_balances_against_error():
    """同错误率的两个解：均衡解惩罚低 → 正则校准应选均衡解。"""
    pairs = _pairs_demo()
    # 均衡解：档位大致均匀；塌缩解：全进一档
    balanced = calibrate_with_regularization(pairs, AlgorithmConfig(), lam=0.5)
    assert balanced is not None
    # 均衡解档位分布应覆盖 ≥3 个档
    dist = {}
    for ds, human in pairs:
        lv = _predict(ds, balanced)
        dist[lv] = dist.get(lv, 0) + 1
    assert len(dist) >= 3, f"正则校准应避免塌缩: {dist}"


def test_calibrate_with_regularization_real_data():
    """真实校准集运行验证（替换默认 bins 逻辑可读性）。"""
    tasks = []
    for name in ("calibration", "mega", "professional", "domain"):
        with open(f"golden_ratio/data/real_suites/{name}.json", encoding="utf-8") as f:
            tasks += json.load(f)["tasks"]
    cfg = AlgorithmConfig()
    pairs = [(compute_shape(build_dag(t["dag_spec"]), cfg).ds, t["human_difficulty"])
             for t in tasks]
    best = calibrate_with_regularization(pairs, cfg, lam=cfg.calib_collapse_lambda)
    assert best is not None and len(best) == 4
