"""v5 验证：5 套件 × 三臂 gd/合规/cv + ΔC-B（交接文档 §8.3 清单）。

复现：python golden_ratio/verify_v5.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from golden_ratio.config import AlgorithmConfig
from golden_ratio.experiment import run_experiment
from golden_ratio.llm import MockLLM

DATA = pathlib.Path(__file__).resolve().parent / "data"

# 套件名 → (数据文件, 期望碎片数字段)
SUITES = {
    "24小任务-T40": ("calibration_tasks.json", "expected_fragments_t40"),
    "24小任务-人工v2": ("calibration_tasks.json", "expected_fragments"),
    "mega12": ("mega_tasks.json", "expected_fragments"),
    "跨领域44": ("domain_tasks.json", "expected_fragments"),
    "专业10": ("professional_tasks.json", "expected_fragments"),
}


def run_suite(fname, key, mode, seed=42, cross=True, b_cap=None, b_ceiling=1.0):
    tasks = json.loads((DATA / fname).read_text(encoding="utf-8"))["tasks"]
    for t in tasks:
        t["expected_fragments"] = t.get(key, t["expected_fragments"])
    cfg = AlgorithmConfig()
    if mode == "hybrid":
        cfg.exp_hybrid_mode = True
    else:
        cfg.exp_hybrid_mode = False        # 显式关闭（config 默认已为 True，必须覆盖）
    cfg.merge_cross_group = cross         # 方案A：跨组合并开关
    cfg.effort_ceiling = b_ceiling        # B微调v5.2：cap软目标系数
    rep = run_experiment(tasks, MockLLM(), cfg, seed=seed,
                         b_cap=(b_cap if b_cap is not None else 40.0))
    arms = rep["arms"]
    return {
        "A_gd": arms["A"]["avg_granularity_deviation"],
        "B_gd": arms["B"]["avg_granularity_deviation"],
        "C_gd": arms["C"]["avg_granularity_deviation"],
        "C_minus_B": round(arms["C"]["avg_granularity_deviation"]
                           - arms["B"]["avg_granularity_deviation"], 4),
        "B_std": arms["B"]["avg_standard_compliance"],
        "C_std": arms["C"]["avg_standard_compliance"],
        "B_cv": arms["B"]["avg_effort_cv"],
        "C_cv": arms["C"]["avg_effort_cv"],
        "C_adaptations": arms["C"]["avg_adaptations"],
    }


def main():
    out = {}
    # 实验矩阵（决策 A vs C）：
    #   crosson-cap40   = A 方案（cross on、cap 统一 40）——已跑数据，此处重跑保持同模板
    #   crossoff-percap = cross off、cap 按口径（隔离 cap 双标尺的独立贡献）
    #   crosson-percap  = C 方案（cross on + cap 按口径）
    combos = [
        ("ce100", 1.0),
        ("ce115", 1.15),
        ("ce130", 1.3),
    ]
    for mode in ("hybrid", "fallback"):
        for tag, ce in combos:
            out[f"{mode}-{tag}"] = {}
            for name, (fname, key) in SUITES.items():
                # 口径归属（v5.1 训练集诊断确定）：
                #  mega/专业期望=健康口径(40h)（T40公式值一致）；跨领域/人工v2期望=8/80合法口径(80h)
                cap = 40.0
                if fname == "domain_tasks.json" or (
                        fname == "calibration_tasks.json" and key != "expected_fragments_t40"):
                    cap = 80.0
                out[f"{mode}-{tag}"][name] = run_suite(fname, key, mode, cross=True, b_cap=cap,
                                                        b_ceiling=ce)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
