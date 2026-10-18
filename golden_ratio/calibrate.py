"""难度分档校准（Q10）：样例集 → 计算 ds → 网格搜索最优 ds_bins（修订稿 §3.1.1⑤）。"""
import itertools
import json
import math
import pathlib

from golden_ratio.difficulty import compute_shape
from golden_ratio.models import DAG, Node

DATA_PATH = pathlib.Path(__file__).resolve().parent / "data" / "calibration_tasks.json"


def load_tasks(path=None):
    p = pathlib.Path(path) if path else DATA_PATH
    return json.loads(p.read_text(encoding="utf-8"))["tasks"]


def build_dag(spec):
    nodes = []
    for i, nd in enumerate(spec["nodes"], start=1):
        nodes.append(Node(
            id=nd.get("id", f"n{i}"), text=nd["text"],
            domain_dist=dict(nd["domain"]),
            trades=list(nd["trades"]),
            complexity=nd["complexity"],
            color_weight=float(nd["weight"]),
            deliverable=nd["deliverable"],
        ))
    if len({n.id for n in nodes}) != len(nodes):
        raise ValueError("节点 id 重复（压力测试发现）")
    ids = {n.id for n in nodes}
    edges = []
    for a, b in spec["edges"]:
        if a not in ids or b not in ids:
            raise ValueError(f"边引用不存在的节点: {a} -> {b}（节点: {sorted(ids)}）")
        edges.append((a, b))
    return DAG(nodes=nodes, edges=edges)


def _predict(ds, bins):
    if ds < bins[0]:
        return 1
    if ds < bins[1]:
        return 2
    if ds < bins[2]:
        return 3
    if ds < bins[3]:
        return 4
    return 5


def _rate(bins, pairs):
    wrong = sum(1 for ds, human in pairs if _predict(ds, bins) != human)
    return wrong / len(pairs)


def _search_bins(pairs, grid):
    best_bins, best_rate = (grid[0],), 1.0
    for combo in itertools.combinations(grid, 4):
        rate = _rate(combo, pairs)
        if rate < best_rate:
            best_bins, best_rate = combo, rate
    return list(best_bins), best_rate


def calibrate(tasks, cfg=None):
    if cfg is None:
        from golden_ratio.config import AlgorithmConfig
        cfg = AlgorithmConfig()

    pairs = []          # (ds, human_difficulty)
    details = []
    for t in tasks:
        dag = build_dag(t["dag_spec"])
        shape = compute_shape(dag, cfg)
        pairs.append((shape.ds, t["human_difficulty"]))
        details.append({"id": t["id"], "ds": shape.ds,
                        "human": t["human_difficulty"]})

    before_rate = _rate(cfg.ds_bins, pairs)

    # 候选切点：排序后相邻 ds 的中点（避免边界重合歧义）
    ds_sorted = sorted(p for p, _ in pairs)
    grid = []
    for a, b in itertools.pairwise(ds_sorted):
        if b - a > 1e-9:
            grid.append(round((a + b) / 2, 4))
    if len(grid) < 4:
        raise ValueError(f"候选切点不足: {len(grid)} < 4")

    best_bins, after_rate = _search_bins(pairs, grid)

    for det, (ds, human) in zip(details, pairs):
        det["before_pred"] = _predict(ds, cfg.ds_bins)
        det["after_pred"] = _predict(ds, best_bins)

    return {
        "best_bins": best_bins,
        "before_rate": round(before_rate, 4),
        "after_rate": round(after_rate, 4),
        "n_tasks": len(tasks),
        "details": details,
    }


if __name__ == "__main__":
    import pathlib
    import sys

    from golden_ratio.config import AlgorithmConfig
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    report = calibrate(load_tasks(), AlgorithmConfig())
    print(json.dumps(report, ensure_ascii=False, indent=1))


# ---- 优化方向2：anti-collapse 正则校准（阶段3 发现：网格最优会塌缩档位）----

def _collapse_metric(pairs, bins):
    """档位塌缩度量：预测档位分布与均匀分布的 KL 散度（0=均分，>0=塌缩）。"""
    import collections
    cnt = collections.Counter(_predict(ds, bins) for ds, _ in pairs)
    n = len(pairs)
    if n == 0:
        return 0.0
    kl = 0.0
    for lv in range(1, 6):
        p = cnt.get(lv, 0) / n
        if p > 0:
            kl += p * math.log(p / 0.2)
    return round(max(0.0, kl), 4)


def collapse_penalty(pairs, bins):
    """对外接口（测试用）：塌缩惩罚 = KL(分布‖均匀)。"""
    return _collapse_metric(pairs, bins)


def calibrate_with_regularization(pairs, cfg, lam=None):
    """anti-collapse 校准：目标 = 错误率 + λ·塌缩惩罚（λ 0 退化为纯错误率）。

    搜索空间与 calibrate 相同（相邻 ds 中点网格 C(n,4)），返回惩罚最优 bins。
    """
    lam = cfg.calib_collapse_lambda if lam is None else lam
    ds_sorted = sorted(p for p, _ in pairs)
    grid = []
    for a, b in itertools.pairwise(ds_sorted):
        if b - a > 1e-9:
            grid.append(round((a + b) / 2, 4))
    if len(grid) < 4:
        raise ValueError(f"候选切点不足: {len(grid)} < 4")
    best_bins, best_obj = None, float("inf")
    for combo in itertools.combinations(grid, 4):
        err = _rate(combo, pairs)
        obj = err + lam * _collapse_metric(pairs, combo)
        if obj < best_obj:
            best_bins, best_obj = list(combo), obj
    return best_bins
