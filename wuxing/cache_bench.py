"""缓存量化基准（P9：每轮量化命中率提升/韧性——用户指定每 round 必测）。

场景：
  repeat   —— 同一任务重复 N 次（日常重复提交）
  similar  —— 任务微改 3 版（用户变体——精确缓存不命中，量化"边界"）
  recovery —— run→中断→resume（恢复场景——R1 主战场）
输出：每场景 hit_rate / calls / calls_without_cache（缓存节省）。
"""
import json
import pathlib
import tempfile

from wuxing.engine import Engine


def _run_with_cache(text, eng):
    eng.reply_cache.hits = 0
    eng.reply_cache.misses = 0
    eng.reply_cache.similar_hits = 0
    eng.shape_cache.hits = 0
    eng.shape_cache.misses = 0
    eng.shape_cache.similar_hits = 0
    eng.run_task(text)
    # P1 T3 口径：语义命中已避免 LLM 调用——从需要调用的计数中扣除
    # （每次语义命中先经历一次精确 miss；misses - similar_hits = 真实 LLM 调用数）
    rc_calls = eng.reply_cache.misses - eng.reply_cache.similar_hits
    sc_calls = eng.shape_cache.misses - eng.shape_cache.similar_hits
    return {"calls": max(0, rc_calls) + max(0, sc_calls)}


def bench_scenarios(n_repeat: int = 5) -> dict:
    base = "写一封请假邮件"
    variants = ["写一封请假邮件", "写请假邮件给经理", "写一封请假邮件 附年假"][:3]
    report = {}

    # repeat：同任务 N 次
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()))
    first = _run_with_cache(base, eng)
    total_calls = first["calls"]
    for _ in range(n_repeat - 1):
        total_calls += _run_with_cache(base, eng)["calls"]
    calls_without = n_repeat * first["calls"]
    report["repeat"] = {
        "hit_rate": round(1 - total_calls / max(1, calls_without), 3),
        "calls": total_calls,
        "calls_without_cache": calls_without,
    }

    # recovery：run（autosave）→ 新引擎 resume（R2 形状化 + R1 回复缓存命中）
    wd = pathlib.Path(tempfile.mkdtemp())
    e1 = Engine(workdir=wd)
    e1.run_task(base)
    e2 = Engine(workdir=wd)
    r_rc = _run_with_cache(base, e2)
    e3 = Engine(workdir=pathlib.Path(tempfile.mkdtemp()))
    base_calls = _run_with_cache(base, e3)["calls"]
    report["recovery"] = {
        "hit_rate": round(1 - r_rc["calls"] / max(1, base_calls), 3),
        "calls": r_rc["calls"],
        "calls_without_cache": base_calls,
    }

    # similar：任务微改变体（精确缓存预期不命中——量化精确边界）
    e4 = Engine(workdir=pathlib.Path(tempfile.mkdtemp()))
    variant_calls = 0
    for v in variants:
        variant_calls += _run_with_cache(v, e4)["calls"]
    # 无缓存基线：独立干净引擎（无缓存命中混入）
    e5 = Engine(workdir=pathlib.Path(tempfile.mkdtemp()))
    one_variant = _run_with_cache(variants[0], e5)["calls"]
    report["similar"] = {
        "hit_rate": round(1 - variant_calls / max(1, len(variants) * one_variant), 3),
        "calls": variant_calls,
        "calls_without_cache": len(variants) * one_variant,
    }

    # similar_drift：标点/空白漂移类（P1 T3 语义缓存——预期命中）
    e6 = Engine(workdir=pathlib.Path(tempfile.mkdtemp()))
    drift_variants = ["写一封请假邮件。", "写一封请假邮件！！", "写一封请假邮件 ！"]
    e6.run_task(base)  # 预置基准
    drift_calls = 0
    for v in drift_variants:
        drift_calls += _run_with_cache(v, e6)["calls"]
    report["similar_drift"] = {
        "hit_rate": round(1 - drift_calls / max(1, len(drift_variants) * one_variant), 3),
        "calls": drift_calls,
        "calls_without_cache": len(drift_variants) * one_variant,
    }
    return report


if __name__ == "__main__":
    print(json.dumps(bench_scenarios(), ensure_ascii=False, indent=2))
