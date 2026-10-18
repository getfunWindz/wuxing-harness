"""阶段 2 验证：真实口径套件 × 三臂矩阵 + 方向/合规/桶密度（零 API 成本）。

用法：python golden_ratio/stage2_verify.py
真实口径套件（stage2_build.py 生成）：data/real_suites/*.json
- calibration：expected_fragments(人工语义保留) + expected_fragments_t40(真实公式重标)
- mega/professional：expected = 真实公式（健康 40h）
- domain：expected = 人工语义（保留）
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from golden_ratio.calibrate import build_dag
from golden_ratio.config import AlgorithmConfig
from golden_ratio.difficulty import compute_shape
from golden_ratio.experiment import (
    BucketAdaptiveRunner,
    arm_config,
    granularity_deviation,
    run_experiment,
)
from golden_ratio.llm import MockLLM

REAL = pathlib.Path(__file__).resolve().parent / "data" / "real_suites"

# (套件, 期望字段, cap) —— 真实套件期望统一公式口径（40h）→ cap 全部 40
SUITES = [
    ("calibration", "expected_fragments_t40", 40.0),
    ("mega", "expected_fragments", 40.0),
    ("professional", "expected_fragments", 40.0),
    ("domain", "expected_fragments", 40.0),
]


def directions(tasks, cfg=None):
    """B 口径方向分布（重标定后的可学习信号检查）。"""
    import collections
    cfg = cfg or arm_config("B", AlgorithmConfig())
    llm = MockLLM()
    dirs = collections.Counter()
    for t in tasks:
        dag = build_dag(t["dag_spec"])
        from golden_ratio.experiment import _run_task
        _, frags, _ = _run_task(dag, cfg, llm)
        gd = granularity_deviation(len(frags), t["expected_fragments"])
        st = "ok" if gd <= cfg.exp_success_threshold else (
            "over" if len(frags) > t["expected_fragments"] else "under")
        dirs[st] += 1
    return dict(dirs)


def bucket_density(tasks, cfg=None):
    cfg = cfg or arm_config("B", AlgorithmConfig())
    runner = BucketAdaptiveRunner(cfg)
    keys = {}
    for t in tasks:
        dag = build_dag(t["dag_spec"])
        shape = compute_shape(dag, cfg)
        keys[runner.bucket_for(shape)] = keys.get(runner.bucket_for(shape), 0) + 1
    n_buckets = len(keys)
    return n_buckets, round(len(tasks) / max(n_buckets, 1), 1)


def main():
    print("== 真实口径三臂矩阵（hybrid + ce115 + drop0.55 + cap 按口径 + 27信标校准 bins）==")
    rows = []
    for name, key, cap in SUITES:
        tasks = json.loads((REAL / f"{name}.json").read_text(encoding="utf-8"))["tasks"]
        for t in tasks:
            t["expected_fragments"] = t.get(key, t["expected_fragments"])
        cfg = AlgorithmConfig()
        cfg.ds_bins = tuple(json.loads((REAL / f"{name}.json").read_text(encoding="utf-8"))
                            ["meta"].get("ds_bins_calibrated", cfg.ds_bins))
        rep = run_experiment(tasks, MockLLM(), cfg, seed=42, b_cap=cap)
        a = rep["arms"]
        label = f"{name}-{key.replace('expected_fragments', '').replace('_', '') or 'formula'}"  # 口径显示修正：期望为公式重标（T/40）
        rows.append((label, a))
        nb, dens = bucket_density(tasks, cfg)
        dirs = directions(tasks, cfg)
        print(f"  {label:24} A={a['A']['avg_granularity_deviation']:.4f} "
              f"B={a['B']['avg_granularity_deviation']:.4f} "
              f"C={a['C']['avg_granularity_deviation']:.4f} "
              f"C-B={round(a['C']['avg_granularity_deviation']-a['B']['avg_granularity_deviation'],4):+.4f} "
              f"std={a['B']['avg_standard_compliance']:.2f} 桶={nb}(密度{dens}) 方向={dirs}")
    return rows


if __name__ == "__main__":
    main()
