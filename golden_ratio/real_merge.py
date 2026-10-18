"""任务2：LLM merge 分组质量实验（真实 DeepSeek merge_nodes vs 确定性 _merge_group）。

成本护栏：仅 calibration 27 任务（代表性子集）→ 27 次 merge 调用。
对比维度：块数 / 8-80 合规 / 无环校验（_validate_groups）/ 与确定性块的差异大小。
用法：export DEEPSEEK_API_KEY=... && python golden_ratio/real_merge.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from golden_ratio.cache import CachedLLM
from golden_ratio.calibrate import build_dag
from golden_ratio.config import AlgorithmConfig
from golden_ratio.difficulty import compute_shape
from golden_ratio.effort import node_effort
from golden_ratio.guard import BudgetGuard
from golden_ratio.models import DAG
from golden_ratio.realllm import DeepSeekLLM
from golden_ratio.segment import _merge_group, _validate_groups

REAL = pathlib.Path(__file__).resolve().parent / "data" / "real_suites"


def main(max_tasks=27, dry=False):
    tasks = json.loads((REAL / "calibration.json").read_text(encoding="utf-8"))["tasks"]
    cfg = AlgorithmConfig()
    cfg.ds_bins = tuple(json.loads((REAL / "calibration.json").read_text(encoding="utf-8"))
                        ["meta"]["ds_bins_calibrated"])
    llm = None if dry else CachedLLM(BudgetGuard(DeepSeekLLM(model="deepseek-v4-flash-vision-exp"),
                                                 max_calls=1))
    rows = []
    for t in tasks[:max_tasks]:
        dag = build_dag(t["dag_spec"])
        shape = compute_shape(dag, cfg)
        id2node = {n.id: n for n in dag.nodes}
        order = [nid for nid in DAG.topological_order(dag)]
        metas = [{"id": nid,
                  "domain": max(id2node[nid].domain_dist, key=id2node[nid].domain_dist.get),
                  "deliverable": id2node[nid].deliverable,
                  "share": 0.5, "effort": node_effort(id2node[nid], shape, cfg)}
                 for nid in order]
        # 确定性块
        cfg._total_effort = shape.total_effort
        det_blocks = _merge_group(metas, cfg, level=shape.difficulty)
        # LLM 块
        if dry:
            llm_blocks, status = det_blocks, "dry"
        else:
            try:
                groups = llm.merge_nodes(metas)
                _validate_groups(groups, dag)
                llm_blocks, status = groups, "ok"
            except Exception as e:
                llm_blocks, status = det_blocks, f"fallback:{type(e).__name__}"
        # 块内工时（用于合规视角）
        def effort_of(block, dag=dag, shape=shape):
            names = {n.id: n for n in dag.nodes}
            return round(sum(node_effort(names[nid], shape, cfg) for nid in block), 1)
        rows.append((t["id"], len(dag.nodes), len(det_blocks), len(llm_blocks), status,
                     [effort_of(b) for b in det_blocks][:4], [effort_of(b) for b in llm_blocks][:4]))
    print(f"{'id':5} {'N':>3} {'det块':>5} {'llm块':>5} {'状态':10} 确定性工时(前4)  LLM工时(前4)")
    for r in rows:
        print(f"{r[0]:5} {r[1]:3} {r[2]:5} {r[3]:5} {r[4]:10} {r[5]}  {r[6]}")
    ok_n = sum(1 for r in rows if r[4] == "ok")
    print(f"\n成功 {ok_n}/{len(rows)}；确定性平均块数 {sum(r[2] for r in rows)/len(rows):.1f}；"
          f"LLM 平均块数 {sum(r[3] for r in rows)/len(rows):.1f}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-tasks", type=int, default=27)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    main(a.max_tasks, a.dry)
