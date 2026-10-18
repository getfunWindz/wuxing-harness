"""阶段 2：真实口径套件生成器（标定基线迁移，零 API 成本）。

决策（算法结构评估报告 §四-阶段2）：
- 人工/语义期望（calibration expected_fragments=专家 v2；domain 套件）→ **保留**
  （期望是"任务该拆几块"的语义判断，与形状化粒度无关）；
- 公式期望（T40=ceil(T/40)；mega/专业=健康 40h 口径）→ **重标**：
  expected = min(ceil(T_real/40), 节点数上限)（T 用真实形状化 DAG 的工作量模型值；
  节点不可再分 → cap 上限，同 T22 教训）；
- 旧 mock 套件不动（回归基线）；新套件存 data/real_suites/。

用法：python golden_ratio/stage2_build.py
"""
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from golden_ratio.calibrate import build_dag
from golden_ratio.config import AlgorithmConfig
from golden_ratio.difficulty import compute_shape

DATA = pathlib.Path(__file__).resolve().parent / "data"
REAL = DATA / "real_suites"

SUITE_MAP = {
    "calibration_tasks.json": ("calibration", ["expected_fragments", "expected_fragments_t40"]),
    "mega_tasks.json": ("mega", ["expected_fragments"]),
    "professional_tasks.json": ("professional", ["expected_fragments"]),
    "domain_tasks.json": ("domain", ["expected_fragments"]),
}


def _formula_exp(shape, n):
    """健康公式口径：ceil(T_real/40)，cap 节点数上限（节点不可再分）。"""
    return min(max(1, math.ceil(shape.total_effort / 40.0)), n)


def build():
    REAL.mkdir(exist_ok=True)
    outs = json.loads((DATA / "real_shape_outputs.json").read_text(encoding="utf-8"))
    summary = []
    for fname, (sid, exp_keys) in SUITE_MAP.items():
        mock_tasks = json.loads((DATA / fname).read_text(encoding="utf-8"))["tasks"]
        by_id = {}
        for k, r in outs["tasks"].items():
            if r.get("ok") and r["suite"] == fname:
                by_id.setdefault(r.get("tid", k.split("-", 1)[1]), r)
        real_tasks = []
        for t in mock_tasks:
            rec = by_id.get(t["id"])
            if rec is None:
                continue
            dag = build_dag(rec["dag_spec"])
            shape = compute_shape(dag, AlgorithmConfig())
            n = len(dag.nodes)
            t_real = {k: v for k, v in t.items()}
            t_real["dag_spec"] = rec["dag_spec"]
            t_real["shape_n_nodes"] = n
            t_real["shape_total_effort_real"] = shape.total_effort
            for k in exp_keys:
                # 全部统一为公式口径（人工语义期望在真实粒度下不可达——阶段2实测修正）
                cold = t.get(k, t.get("expected_fragments"))
                t_real[k] = _formula_exp(shape, n)
                if k == "expected_fragments":
                    t_real["expected_fragments_human"] = cold     # 留痕：人工语义原值（参考非目标）
                    t_real["expected_fragments_method"] = "t40-realformula"
                if k == "expected_fragments_t40":
                    t_real["expected_fragments_t40_mock"] = t.get("expected_fragments_t40")
            real_tasks.append(t_real)
        out_path = REAL / f"{sid}.json"
        out = {"meta": {"source": "real_shape_outputs", "generated_by": "stage2_build.py",
                        "note": "真实形状化 DAG + 公式口径重标定期望（人工语义原值留痕 expected_fragments_human）",
                        "ds_bins_calibrated": [3.542, 4.6915, 4.915, 5.709]},
               "tasks": real_tasks}
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        summary.append((sid, len(real_tasks), out_path.name))
    return summary


if __name__ == "__main__":
    for sid, n, fname in build():
        print(f"{fname:24} {sid:14} {n} 任务（真实形状化 + 重标定）")
