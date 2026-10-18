"""C4（第二轮计划 §2 · 评估 P1）：缓存对照报告——分域/分单元拆解。

口径（用户裁决 2026-10-02 · **全项目唯一口径**）：
- **缓存命中率 = CH = 最近一次有效请求的命中率**（pi footer 同义：
  `cache_read / 完整 prompt`；WUXING 适配器已把 `input` 归一为完整
  prompt 量（openai=prompt_tokens；anthropic=input+read+write），故
  等价式为 `cache_read/input`，**不得**再写成 `cache_read/(input+…)`）。
- 档位（用户裁决 2026-09-12）：≥70% 优秀 / ≥80% 梦幻线。
- 零输入请求不计入「最近一次有效请求」（`input=0` 不参与比率）。
- 旁系对照（须区分命名）：累计 token 加权 Σcache_read/Σinput（非单次均值）。
- 口径说明：缓存命中轮不产生 `llm_call` 事件（trace=实际发生的调用），
  本报告衡量的是「实际发出的调用」。

用法：``python -m wuxing.cache_report <trace.jsonl> [...]``
"""
import argparse
import json
import pathlib

# 口径单一来源（E0-6）：档位/三分/归因纯函数共享 wuxing.usage_tracker
from wuxing.usage_tracker import band_of, call_category, miss_reason


def load_llm_calls(trace_path) -> list:
    """从 trace JSONL 读 llm_call 行（非 llm_call 过滤；损坏行跳过）。"""
    p = pathlib.Path(trace_path)
    if not p.exists():
        return []
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("event") == "llm_call":
                # 真跑修（E0-3）：多 trace 合并分析按 run 分组——unit_id（F-1…）
                # 跨任务复用，仅凭 unit_id 去重会把后续 run 的首调用误归为延续
                row.setdefault("run_key", str(p.parent))
                out.append(row)
    except OSError:
        return []
    return out


def _sums(rows) -> tuple:
    ti = sum(int(r.get("input") or 0) for r in rows)
    tc = sum(int(r.get("cache_read") or 0) for r in rows)
    return ti, tc


def _latest(rows):
    """最近一次有效请求（input>0，调用顺序最后）的 CH（主口径）。"""
    for r in reversed(rows):
        ti = int(r.get("input") or 0)
        if ti <= 0:
            continue
        tc = int(r.get("cache_read") or 0)
        ratio = tc / ti
        return {"input_tokens": ti, "cache_read_tokens": tc,
                "ratio": ratio, "band": band_of(ratio)}
    return None


def _trace_split(rows) -> dict:
    """trace 行 → CH 三分 + miss 归因（与引擎 metrics 同口径，E0-6）。

    - `aux_kind` 行 → 辅助桶（kinds 细分——shape/skill_review/branch_summary）；
    - 其余按 unit_id 分组：组内序 1 → 首调用，其余 → 延续；
    - 无 unit_id 且无 aux_kind 的行不参与拆分（防御历史/异常格式）；
    - input=0 行不参与（不可比率化）。
    """
    valid = [r for r in (rows or []) if int(r.get("input") or 0) > 0]
    buckets = {"first": [], "continuation": [], "auxiliary": []}
    kinds: dict = {}
    seen: set = set()
    for r in valid:
        ak = str(r.get("aux_kind") or "")
        if ak:
            buckets["auxiliary"].append(r)
            kinds[ak] = kinds.get(ak, 0) + 1
            continue
        uid = str(r.get("unit_id") or "")
        if not uid:
            continue
        key = (str(r.get("run_key") or ""), uid)
        if key in seen:
            buckets["continuation"].append(r)
        else:
            seen.add(key)
            buckets["first"].append(r)
    reasons: dict = {}
    for name in ("first", "continuation"):
        for r in buckets[name]:
            rs = miss_reason(r, is_first=(name == "first"))
            if rs:
                reasons[rs] = reasons.get(rs, 0) + 1
    for _r in buckets["auxiliary"]:
        reasons["auxiliary"] = reasons.get("auxiliary", 0) + 1
    out: dict = {"first": call_category(buckets["first"]),
                 "continuation": call_category(buckets["continuation"]),
                 "auxiliary": call_category(buckets["auxiliary"]),
                 "miss_reasons": reasons}
    if out["auxiliary"] is not None:
        out["auxiliary"]["kinds"] = kinds
    return out


def cache_breakdown(calls, group_by: str = "domain") -> dict:
    """token 级总体 + 分组拆解（input=0 的调用剔除——不可比率化）。

    `prompt_tokens` = 完整 prompt 量（= WUXING input 字段之和，已含命中/写入）；
    `ratio` = cache_read/prompt_tokens（pi 同义式——见模块 docstring）。
    """
    valid = [c for c in (calls or []) if int(c.get("input") or 0) > 0]
    # E0-6：主口径/分组保持「单元调用」语义（辅助单列于 ch_split——
    # 与引擎 usage_latest 口径一致；计划 D1：aux 不顶替主展示）
    rows = [c for c in valid if not str(c.get("aux_kind") or "")]
    groups: dict = {}
    for r in rows:
        key = str(r.get(group_by) or "unknown")
        groups.setdefault(key, []).append(r)
    ti, tc = _sums(rows)
    overall = (tc / ti) if ti > 0 else None
    detail = {}
    for name, rs in sorted(groups.items()):
        gti, gtc = _sums(rs)
        detail[name] = {"calls": len(rs), "prompt_tokens": gti,
                        "input_tokens": gti,
                        "cache_read_tokens": gtc,
                        "ratio": (gtc / gti) if gti > 0 else None,
                        "band": band_of((gtc / gti) if gti > 0 else None),
                        "latest": _latest(rs)}
    return {"calls": len(rows), "prompt_tokens": ti,
            "input_tokens": ti, "cache_read_tokens": tc,
            "ratio": overall, "band": band_of(overall),
            "latest": _latest(rows), "ch_split": _trace_split(calls),
            "group_by": group_by, "groups": detail}


def _fmt(ratio) -> str:
    return "—" if ratio is None else f"{ratio * 100:.1f}%"


def _fmt_split_cat(cat) -> str:
    """三分类别 → 单行文本（CLI：CH + 调用数 + kinds）。"""
    if not cat:
        return "—"
    txt = f"{_fmt(cat.get('ratio'))}（{cat.get('calls', 0)} 次）"
    kinds = cat.get("kinds") or {}
    if kinds:
        txt += " [" + ",".join(
            f"{k}×{v}" for k, v in sorted(kinds.items())) + "]"
    return txt


def main() -> int:
    ap = argparse.ArgumentParser(prog="cache-report",
                                 description="缓存 token 级对照报告（C4）")
    ap.add_argument("traces", nargs="+", help="trace.jsonl 路径（可多个——合并）")
    ap.add_argument("--group-by", default="domain",
                    choices=["domain", "unit_id"], help="拆分维度")
    args = ap.parse_args()
    calls = []
    for tp in args.traces:
        calls += load_llm_calls(tp)
    r = cache_breakdown(calls, group_by=args.group_by)
    lt = r["latest"]
    print(f"[cache-report] 缓存命中率（CH·最近请求） {_fmt(lt['ratio'] if lt else None)} "
          f"（{lt['band'] if lt else 'n/a'}；70% 优秀 / 80% 梦幻）")
    print(f"[cache-report] 累计（旁系·Σ/Σ） {_fmt(r['ratio'])}（{r['band'] or 'n/a'}）· "
          f"调用 {r['calls']} · 完整 prompt {r['prompt_tokens']} tok"
          f"（命中 {r['cache_read_tokens']}）")
    for name, g in r["groups"].items():
        glt = g["latest"]
        print(f"  - {name}: CH {_fmt(glt['ratio'] if glt else None)} · "
              f"累计 {_fmt(g['ratio'])}（{g['band']}）· {g['calls']} 次 · "
              f"{g['prompt_tokens']} tok")
    cs = r.get("ch_split") or {}
    if cs.get("first") or cs.get("continuation") or cs.get("auxiliary"):
        print(f"[cache-report] 三分 首调用 {_fmt_split_cat(cs.get('first'))} · "
              f"延续 {_fmt_split_cat(cs.get('continuation'))} · "
              f"辅助 {_fmt_split_cat(cs.get('auxiliary'))}")
    if cs.get("miss_reasons"):
        print("[cache-report] miss 归因 " + " · ".join(
            f"{k} {v}" for k, v in sorted(cs["miss_reasons"].items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
