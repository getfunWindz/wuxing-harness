"""智脑真 LLM A/B 验证（P15：收益实证——Q7-C 默认关的裁决依据）。

方法（P14 结论：mock 无法验证智脑——必须真 LLM + 真实失败分布）：
  两侧引擎（brain_off / brain_on）同一 20 任务序列真 LLM 跑；
  多 API 候选（P15 意图澄清：多模型路由=真实使用场景）——verify 域双候选，
  智脑才有「避开失败模型」的选择空间；单模型下 A/B 结构性无信号。

公平性设计：
  - 形状化：off 侧先跑（形状化入缓存）→ shape_cache.json 复制给 on 侧 →
    on 侧形状化零调用（两侧 DAG 完全一致，差异只来自执行层）
  - 执行层：reply_cache 两侧独立（不共享——否则 on 侧调用数被 off 侧污染）
  - 记忆：brain_memory 仅 on 侧（离线学习无效——在线式：任务 1 只写不读，任务 2+ 有记忆干预）
  - 任务序：固定 seed 均衡抽样（calibration/mega/professional/domain/github）
"""
import argparse
import collections
import json
import pathlib
import random
import shutil
import tempfile

from wuxing.config import EngineConfig
from wuxing.engine import Engine

# P15 意图确认（README 留痕）：用户已接入多 API——DeepSeek 官方 + micuapi 中转站
# （Anthropic 通道 claude-sonnet-5 / OpenAI 通道 gpt-5.6-luna）——真实使用场景
ANTHROPIC_BASE = "https://www.micuapi.ai"
ANTHROPIC_MODEL = "claude-sonnet-5"

_SUITES = [("calibration_tasks", 5), ("mega_tasks", 3),
           ("professional_tasks", 4), ("domain_tasks", 5), ("github_tasks", 3)]


def _sample_tasks(n: int, seed: int = 42) -> list:
    """均衡抽样：各套件按占比取数（ceil 后截断到 n）——套件覆盖不失真。"""
    total_w = sum(w for _, w in _SUITES)
    texts, rng = [], random.Random(seed)
    for fname, weight in _SUITES:
        with open(f"golden_ratio/data/{fname}.json", encoding="utf-8") as f:
            tasks = json.load(f)["tasks"]
        want = max(1, round(weight * n / total_w))
        texts += [t["task_text"] for t in rng.sample(tasks, min(want, len(tasks)))]
    return texts[:n]


def _router_spec(llm_spec, verify_extra: list | None = None) -> dict:
    """多 API 域路由（真实使用场景：国内官方 + 国外中转站均为主流——用户说明）。

    verify 域 = 主模型 + 额外候选（智脑的「选择空间」）；plan/execute = 主模型。
    """
    verify = [llm_spec] + list(verify_extra or [])
    return {"plan": llm_spec, "execute": llm_spec, "verify": verify,
            "_default": llm_spec}


def _run_side(engine: Engine, texts: list, label: str = "") -> dict:
    """单侧跑任务序列，统计指标。（label 进度输出——长跑可见）

    P15 缓存准则（用户底线）：每任务实时打印内部缓存层命中——
    reply 层（执行单元回复缓存）+ shape 层（形状化缓存）；
    此为旁系内部指标，非 LLM token 唯一口径（用户裁决 2026-09-30·pi 同义）。
    """
    status = collections.Counter()
    fails = collections.Counter()
    picked = 0
    usage = collections.Counter()
    for i, t in enumerate(texts, 1):
        r = engine.run_task(t)
        status[r.status] += 1
        for u in r.units:
            mem = (getattr(u, "metrics", None) or {}).get("memory") or {}
            if mem.get("picked_by_brain"):
                picked += 1
            spec = mem.get("spec")
            if spec:
                usage[str(spec)] += 1
            if u.status == "failed":
                from wuxing.repairer import classify_failure
                fails[classify_failure(u.error or "")] += 1
        rc, sc = engine.reply_cache, engine.shape_cache
        total = rc.hits + rc.misses
        rate = (rc.hits / total) if total else 0.0
        stotal = sc.hits + sc.misses
        srate = (sc.hits / stotal) if stotal else 0.0
        print(f"[{label}] {i}/{len(texts)} {r.status} | reply "
              f"H:{rc.hits}/M:{rc.misses} ({rate:.1%}) | shape "
              f"H:{sc.hits}/M:{sc.misses} ({srate:.1%}) | {t[:35]}...", flush=True)
    total = max(1, len(texts))
    rc, sc = engine.reply_cache, engine.shape_cache
    rt = rc.hits + rc.misses
    st = sc.hits + sc.misses
    return {
        "done_rate": round(status.get("done", 0) / total, 3),
        "status_dist": dict(status),
        "calls": rc.misses,        # 执行层 LLM chat 次数（每 miss = 1 次）
        "shape_calls": sc.misses,  # 形状化调用次数
        "failed_dist": dict(fails),
        "brain_picked": picked,
        "model_usage": dict(usage),
        "brain_cases": (len(engine.brain_memory.cases)
                        if getattr(engine, "brain_memory", None) else 0),
        "reply_hits": rc.hits,
        "reply_misses": rc.misses,
        "reply_hit_rate": round(rc.hits / rt, 3) if rt else 0.0,
        "shape_hits": sc.hits,
        "shape_misses": sc.misses,
        "shape_hit_rate": round(sc.hits / st, 3) if st else 0.0,
    }


def ab_compare_real(n_tasks: int = 20, llm_spec="deepseek:deepseek-chat",
                    verify_extra: list | None = None, seed: int = 42,
                    workdir_base: str | None = None,
                    use_real_shape: bool = False) -> dict:
    """真 LLM A/B（结构契约见 test_brain_ab）。

    verify_extra：verify 域额外候选 spec 列表（国外中转站等）——
    候选 ≥2 时智脑才有「避开失败模型」的选择空间（单模型 A/B 结构性无信号）。
    use_real_shape：真形状化（golden_ratio DeepSeek）——***A/B 有效性的必要条件***：
    首轮 A/B 用 mock 形状化（默认）→ 20 任务全部退化单碎片模板、零 verify 域 →
    智脑从未触发选择 → 结果无效（复现边界报告：mock 只测管道）。
    """
    texts = _sample_tasks(n_tasks, seed)
    base = pathlib.Path(workdir_base) if workdir_base else \
        pathlib.Path(tempfile.mkdtemp(prefix="wuxing-ab-"))
    router_spec = _router_spec(llm_spec, verify_extra)
    report = {}

    # --- brain_off 侧（先跑：形状化入缓存 → 复制给 on 侧） ---
    off_wd = base / "brain_off"
    # 第七轮审查：实验隔离——技能自进化显式关闭（防跨侧 skill 落盘污染与
    # 不计数的自评审调用扭曲成本口径）
    off = Engine(cfg=EngineConfig(router=router_spec, use_real_shape=use_real_shape,
                                  skill_evolution_enabled=False),
                 workdir=off_wd, auto_confirm=True)
    report["brain_off"] = _run_side(off, texts, "off")
    # 形状化公平共享：off 的 shape_cache → on（DAG 完全一致，on 侧零形状化调用）
    on_wd = base / "brain_on"
    src = off_wd / "shape_cache.json"
    if src.exists():
        on_wd.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, on_wd / "shape_cache.json")

    # --- brain_on 侧（记忆在线式；Router 由 cfg.router 装配并自动挂 brain） ---
    on = Engine(cfg=EngineConfig(brain_enabled=True, router=router_spec,
                                 use_real_shape=use_real_shape,
                                 skill_evolution_enabled=False),
                workdir=on_wd, auto_confirm=True)
    report["brain_on"] = _run_side(on, texts, "on")

    report["task_list"] = texts[:3]   # 抽样前 3 任务文本（审计/复现用）
    report["config"] = {"n_tasks": len(texts), "seed": seed,
                        "router": router_spec,
                        "workdir": str(base)}
    return report


def _parse_spec(s: str):
    """CLI spec 解析：JSON dict（中转站 base_url 表达）或字符串 spec。"""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return s


def main():
    ap = argparse.ArgumentParser(prog="wuxing-brain-ab")
    ap.add_argument("--n", type=int, default=20, help="任务数（默认 20）")
    ap.add_argument("--llm", default="deepseek:deepseek-chat",
                    help="主模型 spec：字符串（deepseek:deepseek-chat）或 JSON dict（中转站 base_url）")
    ap.add_argument("--extra-candidates",
                    default=json.dumps([
                        {"type": "anthropic", "model": "claude-sonnet-5",
                         "base_url": "https://www.micuapi.ai"},
                        {"type": "openai", "model": "gpt-5.6-luna",
                         "base_url": "https://www.micuapi.ai/v1"},
                    ]),
                    help="verify 域额外候选（JSON 列表——真实场景：国内官方+国外中转站）")
    ap.add_argument("--no-extra", action="store_true",
                    help="verify 域不加额外候选（单模型对照）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workdir-base", default=None, help="A/B 目录基（默认临时）")
    ap.add_argument("--real-shape", action="store_true",
                    help="真形状化（golden_ratio DeepSeek）——A/B 有效性必要条件：\n"
                         "mock 形状化下 20 任务全退化为单碎片模板、零 verify 域、智脑无选择机会")
    args = ap.parse_args()
    llm_spec = _parse_spec(args.llm)
    extra = None if args.no_extra else _parse_spec(args.extra_candidates)
    report = ab_compare_real(n_tasks=args.n, llm_spec=llm_spec,
                             verify_extra=extra, seed=args.seed,
                             workdir_base=args.workdir_base,
                             use_real_shape=args.real_shape)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
