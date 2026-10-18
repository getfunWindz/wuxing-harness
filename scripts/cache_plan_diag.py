#!/usr/bin/env python3
"""Plan 域缓存诊断（B1 · 2026-10-18）。

用途：离线读取 trace JSONL，回答“plan 缓存弱是 system 前缀在变，还是
provider 阈值/调用量结构造成的”。不调用模型、不产生费用。

用法：
  python -m scripts.cache_plan_diag <trace.jsonl> [...]
  python -m scripts.cache_plan_diag --json <trace.jsonl>

输出：
1. plan `llm_call`：调用数 / input / cache_read / CH（token 加权，旁系口径）；
2. plan `prompt_sections`：每个 `sys:*` 节的 distinct 哈希数（>1 = 该节在变）；
3. system 节哈希组合分布（定位“哪些调用共享同一前缀”）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
from collections import Counter

SYS_KEYS = ("sys:contract", "sys:domain", "sys:custom", "sys:tools", "sys:budget")


def _load(path: pathlib.Path) -> list[dict]:
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        pass
    return rows


def summarize(rows: list[dict]) -> dict:
    calls = [r for r in rows
             if r.get("event") == "llm_call"
             and str(r.get("domain") or "") == "plan"]
    total_in = sum(int(r.get("input") or 0) for r in calls)
    total_cache = sum(int(r.get("cache_read") or 0) for r in calls)
    ratio = (total_cache / total_in) if total_in > 0 else None

    sections = [r for r in rows
                if r.get("event") == "prompt_sections"
                and str(r.get("domain") or "") == "plan"]
    distinct: dict[str, int] = {}
    for key in SYS_KEYS:
        values = {(r.get("hashes") or {}).get(key)
                  for r in sections if key in (r.get("hashes") or {})}
        if values:
            distinct[key] = len(values)
    combos = Counter(
        tuple((r.get("hashes") or {}).get(k, "") for k in SYS_KEYS)
        for r in sections
    )
    return {
        "plan_calls": len(calls),
        "input_tokens": total_in,
        "cache_read_tokens": total_cache,
        "ratio": ratio,
        "plan_prompt_sections": len(sections),
        "system_hash_distinct": distinct,
        "system_combo_count": len(combos),
        "system_combo_top": [
            {"count": n, "hashes": dict(zip(SYS_KEYS, combo))}
            for combo, n in combos.most_common(5)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("traces", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows: list[dict] = []
    for name in args.traces:
        rows.extend(_load(pathlib.Path(name)))
    out = summarize(rows)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    print(f"plan calls: {out['plan_calls']} · input={out['input_tokens']} · "
          f"cache_read={out['cache_read_tokens']} · CH={out['ratio']}")
    print(f"plan prompt_sections: {out['plan_prompt_sections']} · "
          f"system combos={out['system_combo_count']}")
    print("system hash distinct:", out["system_hash_distinct"])
    if out["system_hash_distinct"]:
        changed = [k for k, n in out["system_hash_distinct"].items() if n > 1]
        if changed:
            print("→ 变化节：", ", ".join(changed), "（先修这些节的前缀稳定性）")
        else:
            print("→ 所有 system 节哈希稳定：优先怀疑 provider 缓存阈值/plan 调用量结构"
                  "（考虑前缀预热或批次亲和，需真跑验证）")
    for item in out["system_combo_top"]:
        print(f"  combo x{item['count']}: {item['hashes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
