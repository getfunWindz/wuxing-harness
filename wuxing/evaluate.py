"""评测引擎（L1-3 · 知识库「trace=评测原料」+ 指标标准落地）。

指标（与知识库对应）：
  完成率 done_rate          ← 任务状态（Anthropic 九步：定义指标）
  工具正确率 tool_correctness ← trace tool_call 事件 {ok, error, blocked} 分布
  步骤效率 steps_per_unit   ← trace llm_call 数 / 单元数（工具循环型指标）
  重试率 retry_calls        ← 同 (name, arg_hash) 重复调用次数（trace 可判）
  协作契约 delegate_blocked ← delegate 深度/护栏拒绝（多 agent 分型指标）
  验收 verdict_fails        ← verdict_fail 单元数（语义验收）

run_eval：逐任务独立 workdir（trace 隔离）→ 引擎跑 → trace 指标 → 聚合报告。
CLI：python -m wuxing.evaluate [--tasks eval/tasks.v1.json] [--llm SPEC]
     [--n N] [--baseline eval/baseline.json] [--real-shape]
"""
import argparse
import collections
import json
import pathlib
import sys
import tempfile
import time

from wuxing.engine import Engine


def _cache_metrics(usage: dict) -> dict:
    """C-1：服务端缓存批量指标（**旁系**——非唯一口径）。

    唯一口径（用户裁决 2026-10-02）= **CH·最近一次请求命中率**（见
    `wuxing/cache_report.py` 与壳端展示）；本函数对一段 usage 做聚合
    （cache_read_ratio = 累计读占比），仅供批次评测对照——不得简称
    「缓存命中率」。

    档位（用户裁决 2026-09-12）：≥70% 优秀 / ≥80% 梦幻线。
    WUXING input 已归一为完整 prompt 量 → hit/input；DeepSeek miss 字段可用时
    hit/(hit+miss) 为等价式（prompt_tokens=hit+miss）——不一致时官方字段优先（观测口径）。
    """
    inp = int(usage.get("input", 0) or 0)
    cr = int(usage.get("cache_read", 0) or 0)
    _miss = usage.get("cache_miss")
    if _miss is not None:
        _denom = cr + int(_miss)
        ratio = round(cr / _denom, 4) if _denom else 0.0
    else:
        ratio = round(cr / inp, 4) if inp else 0.0
    # 节约估算（参考单价：读 0.1 元/百万 vs 全价 1 元）
    saved = round(cr * 0.9 / 1_000_000, 4) if cr else 0.0
    return {"cache_read_ratio": ratio, "input_tokens": inp,
            "cache_read_tokens": cr, "cache_saved_cost": saved}


def compute_memory_metrics(units: list) -> dict:
    """L3-4：记忆评测——brain 引导命中与成功率（7 步「⑦评测记忆质量」）。

    原料：单元 metrics.memory（router 选择来源标记——L3-4 落 metrics）。
    成功定义：brain 引导单元收敛（status=ok）。真模型 A/B 对比（vs 回退）
    待 LLM 解冻——本指标是「收益」的量化定义。
    """
    picks = [u for u in units
             if (u.metrics or {}).get("memory", {}).get("picked_by_brain")]
    if not picks:
        return {"brain_picks": 0, "brain_pick_success_rate": 0.0,
                "brain_pick_fails": 0}
    ok = sum(1 for u in picks if u.status == "ok")
    return {"brain_picks": len(picks),
            "brain_pick_success_rate": round(ok / len(picks), 4),
            "brain_pick_fails": len(picks) - ok}


def _unit_status(units) -> str:
    """复用引擎任务状态聚合（L0-4 同源——评测口径与运行口径一致）。"""
    return Engine._task_status(units)


def prefix_break_tasks(units: list) -> int:
    """T5：前缀潜坏检测——非首轮 miss（later_round_misses>0）单元计数。

    语义（C-1）：首轮 miss 正常（新任务前缀从不命中）；后续轮 miss 应为 0——
    异常即前缀破坏/毒化残留（如动态内容写入 system、工具集抖动）。
    """
    return sum(1 for u in units
               if (getattr(u, "metrics", None) if not isinstance(u, dict)
                   else u.get("metrics") or {}).get("cache_breakdown", {}).get(
                   "later_round_misses", 0) > 0)


def compute_failure_attribution(units: list, rows: list) -> dict:
    """Task8（真实/能力测试共用）：失败单元归因自动化——harness 自我发现错误。

    分类（优先级：provider > no_llm > contract_never_passed > other）：
      provider_error        —— trace unit_done.provider_error（环境/网络）
      no_llm_call           —— 失败单元零 llm_call（缓存命中后失败/异常）
      contract_never_passed —— 有调用但契约从未通过（预算耗尽型）
      other                 —— 其他
    S1：自动重试会产生多条 unit_done——**取最后一次尝试**（终态分类；
    重试轮不重复计样本：计数单位为单元）。
    同时输出 by_domain 失败分布（哪个域是重灾区）。
    """
    by_unit = {}
    for r in rows or []:
        by_unit.setdefault(r.get("unit_id"), []).append(r)
    out = {"provider_error": 0, "no_llm_call": 0,
           "contract_never_passed": 0, "other": 0, "by_domain": {}}
    for u in units or []:
        if getattr(u, "status", "") != "failed":
            continue
        evs = by_unit.get(getattr(u, "unit_id", ""), [])
        started = next((e for e in evs if e.get("event") == "unit_started"), {})
        dom = started.get("domain") or getattr(u, "domain_id", "?")
        out["by_domain"][dom] = out["by_domain"].get(dom, 0) + 1
        done = next((e for e in reversed(evs)
                     if e.get("event") == "unit_done"), {})
        calls = sum(1 for e in evs if e.get("event") == "llm_call")
        checks = [e for e in evs if e.get("event") == "contract_check"]
        if done.get("provider_error"):
            out["provider_error"] += 1
        elif calls == 0:
            out["no_llm_call"] += 1
        elif checks and not any(c.get("passed") for c in checks):
            out["contract_never_passed"] += 1
        else:
            out["other"] += 1
    return out


def compute_metrics_from_trace(rows: list, units: list) -> dict:
    """trace 事件 → 单元/工具级指标（评测原料加工——确定性，无 LLM）。"""
    llm_calls = [r for r in rows if r.get("event") == "llm_call"]
    tool_calls = [r for r in rows if r.get("event") == "tool_call"]
    tc = {"ok": 0, "error": 0, "blocked": 0}
    for t in tool_calls:
        tc[t.get("status", "error")] = tc.get(t.get("status", "error"), 0) + 1
    # 重试：同 (name, arg_hash) 出现 >1 次的超额次数
    seq = collections.Counter((t.get("name"), t.get("arg_hash"))
                              for t in tool_calls)
    retry = sum(v - 1 for v in seq.values() if v > 1)
    delegate_blocked = sum(
        1 for t in tool_calls
        if t.get("name") == "delegate" and t.get("status") == "blocked")
    verdict_fails = sum(1 for u in units if getattr(u, "verdict_fail", False))
    n_units = max(1, len(units))
    ok_units = sum(1 for u in units if u.status == "ok")
    return {
        "task_status": _unit_status(units),
        "unit_ok_rate": round(ok_units / n_units, 4),
        "llm_calls": len(llm_calls),
        "steps_per_unit": round(len(llm_calls) / n_units, 2),
        "tool_correctness": tc,
        "tools_total": len(tool_calls),
        "tool_error_rate": round(
            (tc.get("error", 0) + tc.get("blocked", 0)) / max(1, len(tool_calls)),
            4),
        "retry_calls": retry,
        "delegate_blocked": delegate_blocked,
        "verdict_fails": verdict_fails,
    }


def run_eval(tasks: list, llm=None, real_shape: bool = False,
             workdir_base: str | None = None) -> dict:
    """评测集统一入口：逐任务跑（独立 workdir——trace/缓存互不污染）→ 聚合指标。

    llm：provider 实例或**可调用工厂**（每任务新建——测试/真模型注入）；
    None = Mock（管道级）。
    real_shape：真形状化（golden_ratio DeepSeek——需 key；默认 mock 管道）。
    """
    base = pathlib.Path(workdir_base) if workdir_base else \
        pathlib.Path(tempfile.mkdtemp(prefix="wuxing-eval-"))
    per_task = []

    def _make_llm():
        """llm 参数：None=mock / callable=工厂（每任务新建）/ spec=str|dict→工厂。"""
        if llm is None:
            return None
        if callable(llm):
            return llm()
        from wuxing.llm.factory import create_provider
        return create_provider(llm)

    for t in tasks:
        wd = base / f"{t.get('id', 'T')}"
        wd.mkdir(parents=True, exist_ok=True)
        from wuxing.config import EngineConfig
        eng = Engine(cfg=EngineConfig(use_real_shape=real_shape), workdir=wd,
                     llm=_make_llm(), auto_confirm=True)
        res = eng.run_task(t["task_text"])
        rows = eng.trace.load() if eng.trace else []
        m = compute_metrics_from_trace(rows, res.units)
        # T5：前缀潜坏信号（后续轮 miss>0 单元数——缓存回归可检测）
        m["cache_prefix_breaks"] = prefix_break_tasks(res.units)
        # Task8：失败归因自动化（provider/no_llm/contract——harness 自我发现错误）
        m["failure_attribution"] = compute_failure_attribution(res.units, rows)
        # C-1：缓存指标（评测聚合——目标 90/95/99.5 量化）
        m["cache"] = _cache_metrics((res.metrics or {}).get("usage", {}))
        _rc = (res.metrics or {}).get("cache", {}).get("reply", {})
        _sc = (res.metrics or {}).get("cache", {}).get("shape", {})
        rt = _rc.get("hits", 0) + _rc.get("misses", 0)
        st = _sc.get("hits", 0) + _sc.get("misses", 0)
        m["cache"]["reply_hit_rate"] = round(_rc.get("hits", 0) / rt, 3) if rt else 0.0
        m["cache"]["shape_hit_rate"] = round(_sc.get("hits", 0) / st, 3) if st else 0.0
        per_task.append({"id": t.get("id", ""), "suite": t.get("suite", ""),
                         "status": res.status, "metrics": m})
    total = max(1, len(tasks))
    agg = collections.Counter()
    tools_sum = {"ok": 0, "error": 0, "blocked": 0}
    for pt in per_task:
        agg[pt["status"]] += 1
        for k in tools_sum:
            tools_sum[k] += pt["metrics"]["tool_correctness"].get(k, 0)
    done = agg.get("done", 0)
    steps = [pt["metrics"]["steps_per_unit"] for pt in per_task]
    retries = sum(pt["metrics"]["retry_calls"] for pt in per_task)
    tools_total = sum(tools_sum.values())
    # C-1：缓存聚合（服务端占比按任务均值 + reply/shape 命中率）
    ratios = [pt["metrics"]["cache"]["cache_read_ratio"] for pt in per_task]
    rep = [pt["metrics"]["cache"]["reply_hit_rate"] for pt in per_task]
    shp = [pt["metrics"]["cache"]["shape_hit_rate"] for pt in per_task]
    cache_agg = {"avg_cache_read_ratio": round(sum(ratios) / len(ratios), 4)
                 if ratios else 0.0,
                 "avg_reply_hit_rate": round(sum(rep) / len(rep), 4) if rep else 0.0,
                 "avg_shape_hit_rate": round(sum(shp) / len(shp), 4) if shp else 0.0}
    return {
        "n_tasks": len(tasks),
        "status_dist": dict(agg),
        # T1（用户裁决 2026-09-07）：缓存口径=任务内复用——per-task usage
        # 独立计算（跨任务前缀物理不可达；口径显式声明防语义漂移）
        "cache_scope": "task-internal",
        "metrics": {
            "done_rate": round(done / total, 4),
            "avg_steps_per_unit": round(
                sum(steps) / len(steps), 2) if steps else 0.0,
            "tool_correctness": tools_sum,
            "tools_total": tools_total,
            "tool_error_rate": round(
                (tools_sum["error"] + tools_sum["blocked"]) / max(1, tools_total),
                4),
            "retry_calls": retries,
            "delegate_blocked": sum(
                pt["metrics"]["delegate_blocked"] for pt in per_task),
            "verdict_fails": sum(
                pt["metrics"]["verdict_fails"] for pt in per_task),
            "cache_prefix_breaks": sum(
                pt["metrics"].get("cache_prefix_breaks", 0)
                for pt in per_task),
        },
        "cache": cache_agg,
        "workdir": str(base),
        "tasks": per_task,
    }


def main():
    ap = argparse.ArgumentParser(
        prog="wuxing-evaluate",
        description="能力测试（capability test）：固定任务集验证机制正确性/回归"
                    "——测的不是缓存命中率与真实使用体验（那些看「真实测试」：chat 会话）。")
    ap.add_argument("--tasks", default=None, help="评测集路径（默认 eval/tasks.v1.json）")
    ap.add_argument("--llm", default="mock", help="provider spec（deepseek:... 等）")
    ap.add_argument("--n", type=int, default=0, help="取前 N 条（0=全部）")
    ap.add_argument("--real-shape", action="store_true", help="真形状化（需 key）")
    ap.add_argument("--baseline", default=None, help="基线 JSON 对比（缺失不阻断）")
    ap.add_argument("--out", default=None,
                    help="报告落盘路径（默认 eval/eval_v4flash{时间戳}.json——举证可追溯）")
    ap.add_argument("--ids", default=None,
                    help="指定任务 ID 集合（逗号分隔——部分重跑/断连续跑）")
    args = ap.parse_args()

    from wuxing.eval_set import load_eval_tasks
    tasks = load_eval_tasks(args.tasks)
    if args.ids:
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        tasks = [t for t in tasks if t["id"] in want]
        missing = want - {t["id"] for t in tasks}
        if missing:
            print(f"[eval] 警告: ids 未匹配任务 {sorted(missing)}", file=sys.stderr)
    elif args.n:
        tasks = tasks[:args.n]
    # L4/GLM：--llm 支持 JSON dict spec（智谱等 base_url 表达）——同 brain_ab._parse_spec
    if args.llm == "mock":
        llm = None
    else:
        try:
            llm = json.loads(args.llm)
        except (json.JSONDecodeError, TypeError):
            llm = args.llm
    report = run_eval(tasks, llm=llm, real_shape=args.real_shape)
    out = {"version": "v1", "llm": args.llm, "real_shape": args.real_shape,
           "items": report}
    if args.baseline and pathlib.Path(args.baseline).exists():
        try:
            base = json.loads(pathlib.Path(args.baseline).read_text(
                encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            base = None
        if base:
            out["diff"] = {
                k: {"now": report["metrics"].get(k),
                    "baseline": base.get("metrics", {}).get(k)}
                for k in ("done_rate", "tool_error_rate", "avg_steps_per_unit",
                          "retry_calls")}
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    # G1（2026-09-07）：评测报告持久化——stdout 管道截断即丢（证据不可再生）
    out_path = args.out or str(pathlib.Path("eval") / f"eval_v4flash{int(time.time())}.json")
    try:
        pathlib.Path(out_path).write_text(
            json.dumps(out, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        print(f"[eval] 报告已落盘: {out_path}")
    except (OSError, ValueError):
        print(f"[eval] 警告: 报告写盘失败（{out_path}）——仅 stdout 输出")


if __name__ == "__main__":
    main()
