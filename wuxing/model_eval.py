"""多模型评分框架（4b——用户方法论纠偏：测试任务不 A/B 对测）。

黄金分割率标准（用户指正）：切割粒度有区间（不是每次一样）——每个模型在
harness 上独立跑评估集 → 多维评分（形状化契约合规/粒度区间命中/执行完成/
失败归因/成本/缓存）→ 评分分析比对（评分对象 = 模型×harness 组合表现，
不是模型间对决）。

与 brain_ab 的区别：无智脑开关比较——单模型起评分（智脑维持默认关，
其收益另议）；评估集复用均衡抽样（seed 固定可复现）。
"""
import argparse
import collections
import json
import pathlib
import tempfile

from wuxing.brain_ab import _sample_tasks
from wuxing.config import EngineConfig
from wuxing.engine import Engine


def evaluate_model(llm_spec="deepseek:deepseek-chat", n_tasks: int = 20,
                   seed: int = 42, use_real_shape: bool = True,
                   workdir_base: str | None = None) -> dict:
    """单模型在 harness 上的表现评分（多维度）。

    llm_spec：模型 spec（str 或 dict）；use_real_shape 默认 True——
    mock 形状化只测管道（P15 教训）——评分必须真形状化。
    """
    texts = _sample_tasks(n_tasks, seed)
    if llm_spec == "mock":
        use_real_shape = False  # mock 只测管道（结构测试）；真实评分 CLI 用真形状化
    base = pathlib.Path(workdir_base) if workdir_base else \
        pathlib.Path(tempfile.mkdtemp(prefix="wuxing-eval-"))
    eng = Engine(cfg=EngineConfig(use_real_shape=use_real_shape,
                                  llm=llm_spec if isinstance(llm_spec, str) else "mock",
                                  router={} if isinstance(llm_spec, dict) else None),
                 workdir=base)
    if isinstance(llm_spec, dict):
        # dict spec（中转站 base_url 等）：装到 router 的 _default
        from wuxing.llm.router import ModelRouter
        eng.router = ModelRouter({"_default": llm_spec})
        eng._llm = None  # Engine 已用 router 路径——占位（llm_for 走 router）
    status = collections.Counter()
    unit_fails = collections.Counter()
    gran_in = gran_total = 0
    shape_ok = shape_fail = 0
    # 粒度区间判定需要 golden_ratio 管道（sp 形状化缓存中重建 DAG）
    _gr_loaded = {}
    for i, t in enumerate(texts, 1):
        r = eng.run_task(t)
        status[r.status] += 1
        print(f"[eval:{str(llm_spec)[:22]}] {i}/{len(texts)} {r.status} | {t[:30]}...",
              flush=True)  # 后台可见进度（长跑）
        # 形状化层成功/失败（shape-error 任务 fragments 为空）
        if r.status == "failed" and not r.fragments:
            shape_fail += 1
        else:
            shape_ok += 1
        # 粒度区间（8/80 语义）：碎片工时落在 [8,80] 的比例
        if not _gr_loaded:
            from golden_ratio.calibrate import build_dag
            from golden_ratio.config import AlgorithmConfig
            from golden_ratio.difficulty import compute_shape
            from golden_ratio.effort import effort_bounds, fragment_effort
            from golden_ratio.llm import MockLLM as GrMock
            from golden_ratio.segment import segment
            _gr_loaded.update(build_dag=build_dag, compute_shape=compute_shape,
                              segment=segment, effort_bounds=effort_bounds,
                              fragment_effort=fragment_effort,
                              cfg=AlgorithmConfig(), gmock=GrMock())
        cached = eng.shape_cache.get(t)
        if cached:
            dag = _gr_loaded["build_dag"](cached)
            shape = _gr_loaded["compute_shape"](dag, _gr_loaded["cfg"])
            frags = _gr_loaded["segment"](dag, shape, _gr_loaded["gmock"])
            lo, hi = _gr_loaded["effort_bounds"](_gr_loaded["cfg"], shape.total_effort)
            for f in frags:
                e = _gr_loaded["fragment_effort"](f, dag.nodes, shape, _gr_loaded["cfg"])
                gran_total += 1
                if lo <= e <= hi:   # 动态区间（小任务 min(8,T/4) 收紧——v3.0 语义）
                    gran_in += 1
        for u in r.units:
            if u.status == "failed":
                from wuxing.repairer import classify_failure
                unit_fails[classify_failure(u.error or "")] += 1
    total = max(1, len(texts))
    rc = eng.reply_cache
    rt = rc.hits + rc.misses
    return {
        "model": str(llm_spec),
        "n_tasks": len(texts),
        "shape_ok": shape_ok,
        "shape_fail": shape_fail,
        "shape_compliance": round(shape_ok / total, 3),
        "gran_in_interval": gran_in,          # 粒度区间命中（阶段 4 完善：要 fragment_effort）
        "gran_total": gran_total,
        "done_rate": round(status.get("done", 0) / total, 3),
        "status_dist": dict(status),
        "unit_failed_dist": dict(unit_fails),
        "calls": rc.misses,
        "shape_calls": eng.shape_cache.misses,
        "cache_reply_hit_rate": round(rc.hits / rt, 3) if rt else 0.0,
    }


def compare_models(specs: list, **kw) -> list:
    """多模型评分对比表（模型 × harness 组合表现——评分分析，非 A/B）。"""
    out = []
    for spec in specs:
        out.append(evaluate_model(llm_spec=spec, **kw))
    return out


def main():
    ap = argparse.ArgumentParser(prog="wuxing-model-eval")
    ap.add_argument("--models", nargs="+", default=["deepseek:deepseek-chat"],
                    help="模型 spec 列表（str 或 JSON dict）")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workdir-base", default=None)
    args = ap.parse_args()
    specs = []
    for m in args.models:
        try:
            specs.append(json.loads(m))
        except json.JSONDecodeError:
            specs.append(m)
    print(json.dumps(compare_models(specs, n_tasks=args.n, seed=args.seed,
                                    workdir_base=args.workdir_base),
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
