"""A2（2026-09-22）：碎片消息三键裁剪——投影层应用（omit/replace）。

三键：`index`（定位提示）+ `fp_in`（提示词输入指纹）+ `fp_out`（模型实际输出指纹）。
应用规则（用户裁决）：**双指纹任一命中即视为同一目标**（可选其一或两项都达成）；
均不命中 → 跳过（防护优先，不误裁）；多项命中 → `index` 最近者生效。
纪律：仅影响注入投影（池/存档零改写）；指纹算法与 `context_sources.content_fp` 同源。
"""
from __future__ import annotations

from wuxing.context_sources import content_fp


def apply_unit_edits(messages: list, edits: list) -> tuple:
    """应用 unit 编辑 → (新消息列表, 未命中的跳过列表)。确定性；不改写入参。"""
    msgs = [dict(m) for m in (messages or [])]
    omit: set = set()
    replace: dict = {}
    skipped: list = []
    for e in (edits or []):
        try:
            idx = int(e.get("index"))
        except (TypeError, ValueError):
            idx = -1
        fp_in = str(e.get("fp_in") or "")
        fp_out = str(e.get("fp_out") or "")
        target = None
        best = None
        for i, m in enumerate(msgs):
            fp = content_fp(m.get("content", ""))
            if fp == "" or (fp != fp_in and fp != fp_out):
                continue
            dist = abs(i - idx) if idx >= 0 else 0
            if best is None or dist < best:
                best, target = dist, i
        if target is None:
            skipped.append(e)
            continue
        if str(e.get("op") or "") == "omit":
            omit.add(target)
            replace.pop(target, None)
        else:
            replace[target] = str(e.get("content") or "")
            omit.discard(target)
    out: list = []
    for i, m in enumerate(msgs):
        if i in omit:
            continue
        if i in replace:
            out.append({**m, "content": replace[i]})
        else:
            out.append(m)
    return out, skipped
