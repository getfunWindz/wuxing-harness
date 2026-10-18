"""usage 追踪器（R2 拆分 Phase 2——从 runner 提取：usage 段读取单一职责）。

B12（2026-09-07）：thread-local 段——并发碎片各记各的（不串入）；假 LLM
（无 provider API）回退历史差分（顺序语义）。
"""


class UsageTracker:
    """单元/轮次 usage 段读取（provider thread-local 优先，假 LLM 差分回退）。"""

    def __init__(self, llm):
        self._llm = llm
        self._take = getattr(llm, "_take_usage_since", None)
        self._fb_start = None  # 假 LLM 回退游标（无 provider API 时）

    def snapshot(self) -> int:
        """调用前快照（provider API 或假 LLM 差分起点）。"""
        if self._take is not None:
            return self._llm._usage_snapshot()
        if self._fb_start is None:
            self._fb_start = len(getattr(self._llm, "usage_history", []))
        return self._fb_start

    def since(self, snap: int) -> list:
        """[snap, now) 的 usage 段（本线程调用序列——并发安全）。"""
        if self._take is not None:
            return self._take(snap)
        hist = getattr(self._llm, "usage_history", [])
        return hist[snap:]

    @staticmethod
    def aggregate(used: list) -> dict:
        """usage 段 → 汇总（slot 缺失补 0；cache_miss 仅在出现时输出）。"""
        total = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        has_miss = False
        miss = 0
        has_rt = False
        rt = 0
        for u in used:
            for k in total:
                total[k] += u.get(k, 0)
            if u.get("cache_miss") is not None:
                has_miss = True
                miss += int(u["cache_miss"])
            if u.get("reasoning_tokens") is not None:
                has_rt = True
                rt += int(u["reasoning_tokens"])
        if has_miss:
            total["cache_miss"] = miss
        if has_rt:
            total["reasoning_tokens"] = rt
        return total


# ---- E0-6：CH 口径共享纯函数（单一来源——cache_report/runner/engine 复用）----
GOOD = 0.7
DREAM = 0.8


def band_of(ratio) -> str:
    """比率 → 档位（"" = 无数据）。口径单一来源（用户裁决 2026-09-12 档位）。"""
    if ratio is None:
        return ""
    if ratio >= DREAM:
        return "dream"
    if ratio >= GOOD:
        return "good"
    return "below"


def miss_reason(usage: dict, is_first: bool, is_aux: bool = False):
    """miss 归因（likely cause 粗分）：桶名或 None（健康/不可比率化）。

    - 辅助调用 → "auxiliary"（独立前缀）；
    - 首调用 ratio<0.7 → "new_session"（新会话首批）；
    - 延续 ratio<0.7 → "prefix_change"（前缀变更：摘要/历史/工具定义等）；
    - ratio≥0.7 视为健康不归因（首调用命中好 = FSC 延续——正信号）。
    """
    if is_aux:
        return "auxiliary"
    inp = int((usage or {}).get("input") or 0)
    if inp <= 0:
        return None
    ratio = int(usage.get("cache_read") or 0) / inp
    if ratio >= GOOD:
        return None
    return "new_session" if is_first else "prefix_change"


def call_category(rows: list):
    """调用子集 → 类别结构（无调用 → None）——split/trace 报告共享。"""
    if not rows:
        return None
    ti = sum(int(r.get("input") or 0) for r in rows)
    tc = sum(int(r.get("cache_read") or 0) for r in rows)
    ratio = (tc / ti) if ti > 0 else None
    return {"calls": len(rows), "prompt_tokens": ti,
            "cache_read_tokens": tc, "ratio": ratio, "band": band_of(ratio)}


def split_calls(used: list) -> dict:
    """单元调用序列 → 首调用/延续三分 + miss 归因（首=序 1，续=其余）。"""
    used = [u for u in (used or []) if isinstance(u, dict)]
    reasons: dict = {}
    for i, u in enumerate(used):
        r = miss_reason(u, is_first=(i == 0))
        if r:
            reasons[r] = reasons.get(r, 0) + 1
    return {"first": call_category(used[:1]),
            "continuation": call_category(used[1:]),
            "miss_reasons": reasons}


def trace_llm_call(trace, unit_id, domain_id, round_no, latency_ms, used,
                   extra: dict | None = None):
    """LLM 轮次 trace（latency + 本轮 usage 增量真值——缓存命中轮不调用）。

    extra：附加字段（Task7：conversation_round——真实测试埋点）。
    """
    if trace is None:
        return
    totals = UsageTracker.aggregate(used)
    trace.log("llm_call", unit_id, domain_id, round=round_no,
              latency_ms=latency_ms, **(extra or {}), **totals)
