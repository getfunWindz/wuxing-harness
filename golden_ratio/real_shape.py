"""真 LLM 形状化批量脚本（成本可控接入演练）。

流程：套件任务文本 → CachedLLM(落盘缓存) → BudgetGuard(3次/任务) →
DeepSeekLLM(model=flash-vision-exp) → validate 结构校验 → 命中即信任 / 非法重试一次。

成本护栏（用户决策：控制成本）：
1. 预算护栏：每任务 shape_task ≤ 3 次真实调用（重试=非法/网络异常）；
2. 结构校验替代全量稳定性采样（合法即信任单次输出）；
3. 落盘缓存：outputs.json 已存在的任务跳过（断点续跑，重复执行零新增成本）；
4. 输出裁剪：仅保存 normalized DAG（不存原始冗长响应）。

用法：
  python golden_ratio/real_shape.py --suite all --max-tasks 3   # 小样本先验证
  python golden_ratio/real_shape.py --suite all                  # 全量
  python golden_ratio/real_shape.py --report                     # 只出对比报告（不调 API）

依赖 env：DEEPSEEK_API_KEY（必填）；DEEPSEEK_BASE_URL（可选，默认官方）。
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from golden_ratio.cache import CachedLLM
from golden_ratio.guard import BudgetExceeded, BudgetGuard
from golden_ratio.realllm import DeepSeekLLM
from golden_ratio.validate import validate_shape_output

DATA = pathlib.Path(__file__).resolve().parent / "data"
OUT = DATA / "real_shape_outputs.json"

SUITES = {
    "calibration": ("calibration_tasks.json", "task_text"),
    "mega": ("mega_tasks.json", "task_text"),
    "domain": ("domain_tasks.json", "task_text"),
    "professional": ("professional_tasks.json", "task_text"),
    "github": ("github_tasks.json", "task_text"),
}


def load_outs():
    if OUT.exists():
        outs = json.loads(OUT.read_text(encoding="utf-8"))
        # 迁移 v1：裸 id key → f"{suite}-{tid}"（修复跨套件 id 碰撞：T10 属于 calibration+domain）
        migrated = {}
        for k, rec in outs.get("tasks", {}).items():
            if "-" in k or "suite" not in rec:
                rec2 = dict(rec)
                rec2["tid"] = k if "-" not in k else k.split("-", 1)[1]
                migrated[(rec2.get("suite", "?"), rec2["tid"])] = rec2
            else:
                rec2 = dict(rec)
                rec2["tid"] = k
                migrated[(rec2["suite"], rec2["tid"])] = rec2
        outs["tasks"] = {f"{s.split('.')[0]}-{t}": r for (s, t), r in migrated.items()}
        return outs
    return {"meta": {"model": "deepseek-v4-flash-vision-exp", "note": ""}, "tasks": {}}


def key_of(fname, tid):
    return f"{fname.split('.')[0]}-{tid}"


def save_outs(outs):
    OUT.write_text(json.dumps(outs, ensure_ascii=False, indent=1), encoding="utf-8")


def build_llm(model="deepseek-v4-flash-vision-exp", max_calls=3):
    inner = DeepSeekLLM(model=model)
    guard = BudgetGuard(inner, max_calls=max_calls)
    cached = CachedLLM(guard, max_entries=500)
    return cached, guard


def to_spec_format(norm_nodes):
    """LLM 输出节点 → 样例 dag_spec 格式（兼容层，契约单一来源见 contract.py）。"""
    from golden_ratio.contract import llm_to_spec
    return llm_to_spec(norm_nodes)


def run_suite(fname, llm, outs, max_tasks=None, dry=False, guard=None):
    tasks = json.loads((DATA / fname).read_text(encoding="utf-8"))["tasks"]
    done, skipped, failed = [], [], []
    n = len(tasks)
    for i, t in enumerate(tasks):
        if max_tasks and i >= max_tasks:
            break
        tid = t["id"]
        key = key_of(fname, tid)
        if key in outs["tasks"] and outs["tasks"][key].get("ok"):
            skipped.append(tid)
            continue
        if dry:
            continue
        # 预算护栏语义：每任务一个预算周期（重试 ≤ max_calls 次）
        if guard is not None:
            guard.reset()
        raw, ok, errs = None, False, []
        try:
            raw = llm.shape_task(t["task_text"])
            ok, norm, errs = validate_shape_output(raw)
            if not ok:
                # 轻量修复：孤立根挂前驱（成本优先：修复成功省一次重试调用）
                from golden_ratio.validate import repair_dag
                nodes, edges, changed = repair_dag(raw)
                if changed:
                    ok, norm, errs = validate_shape_output(
                        {"nodes": nodes, "edges": edges, "total_size": raw.get("total_size", 1.0)})
        except BudgetExceeded as e:
            failed.append((tid, f"BudgetExceeded: {e}"))
            continue
        except Exception as e:
            failed.append((tid, f"{type(e).__name__}: {e}"))
            continue
        if ok:
            from golden_ratio.calibrate import build_dag
            from golden_ratio.config import AlgorithmConfig
            from golden_ratio.difficulty import compute_shape
            spec_nodes = to_spec_format(norm["nodes"])
            dag = build_dag({"nodes": spec_nodes, "edges": norm["edges"]})
            shape = compute_shape(dag, AlgorithmConfig())
            outs["tasks"][key] = {
                "ok": True,
                "suite": fname,
                "n_nodes": len(norm["nodes"]),
                "n_edges": len(norm["edges"]),
                "difficulty": shape.difficulty,
                "ds": shape.ds,
                "domain_max": max(shape.domain_dist, key=shape.domain_dist.get),
                "dag_spec": {"nodes": spec_nodes, "edges": norm["edges"]},
            }
            done.append(tid)
        else:
            failed.append((tid, f"validate: {errs[:2]}"))
    return done, skipped, failed, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="all", choices=list(SUITES) + ["all"])
    ap.add_argument("--max-tasks", type=int, default=None)
    ap.add_argument("--model", default="deepseek-v4-flash-vision-exp")
    ap.add_argument("--dry", action="store_true", help="不调 API，仅演练流程/统计待跑数")
    ap.add_argument("--report", action="store_true", help="仅输出对比统计（mock dag_spec vs 真实形状化）")
    args = ap.parse_args()

    outs = load_outs()
    outs["meta"]["model"] = args.model

    if args.report:
        make_report(outs)
        return

    suites = SUITES.items() if args.suite == "all" else [(args.suite, SUITES[args.suite])]
    need_key = not args.dry
    if need_key:
        import os
        if not os.environ.get("DEEPSEEK_API_KEY"):
            print("❌ 未设置 DEEPSEEK_API_KEY（成本警示：请确认后设置再运行）")
            return
    llm, guard = build_llm(model=args.model) if not args.dry else (None, None)

    for sname, (fname, _) in suites:
        done, skipped, failed, n = run_suite(fname, llm, outs, max_tasks=args.max_tasks, dry=args.dry, guard=guard)
        print(f"[{sname}] 共{n} 完成{len(done)} 缓存跳过{len(skipped)} 失败{len(failed)}")
        for tid, err in failed:
            print(f"   ✗ {tid}: {err}")
    save_outs(outs)
    print(f"✓ 已写入 {OUT}")


def make_report(outs):
    """对比报告：真实形状化 vs mock 校准 dag_spec（节点数/难度/领域分布）。"""
    import collections
    print("== 真实形状化覆盖统计 ==")
    by_suite = collections.defaultdict(list)
    for rec in outs["tasks"].values():
        if rec.get("ok"):
            by_suite[rec["suite"]].append(rec)
    for suite, recs in sorted(by_suite.items()):
        print(f"  {suite}: {len(recs)} 个真实形状化")
        print(f"    节点数: {collections.Counter(r['n_nodes'] for r in recs)}")
        print(f"    难度档: {collections.Counter(r['difficulty'] for r in recs)}")
        print(f"    主领域: {collections.Counter(r['domain_max'] for r in recs)}")
    print("== 与 mock 校准对比（calibration 套件） ==")
    calib = json.loads((DATA / "calibration_tasks.json").read_text(encoding="utf-8"))["tasks"]
    for t in calib:
        rec = outs["tasks"].get(t["id"])
        if rec and rec.get("ok"):
            mock_n = len(t["dag_spec"]["nodes"])
            real_n = rec["n_nodes"]
            flag = "← 差异" if mock_n != real_n else ""
            print(f"  {t['id']}: mock {mock_n}节点 / real {real_n}节点  L_real={rec['difficulty']} {flag}")


if __name__ == "__main__":
    main()
