"""Engine 度量子系统（骨架分期 P3/F-3b：自 engine.py 提取的方法组）。

来源：`wuxing/engine.py`（2026-10-06 迁移；方法体逐字节保持）。
理由：F-3 巨型文件分期——度量/用量/成本面落隔离模块（S-2 mixin 裁定）；engine 只做类基接线。
依赖：经 `self` 访问引擎状态（reply_cache/shape_cache/session_pool/_aux_calls）；**不得 import engine**（守卫）。
"""
import logging
import time

logger = logging.getLogger(__name__)


class EngineMetricsMixin:
    def _cache_snapshot(self) -> dict:
        """P1 T4：缓存计数器快照（任务级差值）。"""
        rc, sc = self.reply_cache, self.shape_cache
        return {"rh": rc.hits, "rm": rc.misses, "rs": rc.similar_hits,
                "sh": sc.hits, "sm": sc.misses, "ss": sc.similar_hits}

    def _pool_snapshot(self) -> dict | None:
        """阶段 4（对齐项⑩）：FSC 会话池计数快照（任务级差值）。"""
        pool = getattr(self, "session_pool", None)
        return pool.stats() if pool is not None else None

    def _task_start_snapshot(self) -> dict:
        """任务开始快照：缓存 + FSC 池基线（度量口径；重置辅助账目 E0-6）。"""
        self._pool_baseline = self._pool_snapshot()
        self._aux_calls = []        # E0-6：单元外调用账目（shape/评审/分支摘要）
        self._aux_merged_upto = 0   # 尾差合并游标（技能评审晚于 metrics 构建）
        return self._cache_snapshot()

    def _record_aux_call(self, kind: str, used: list,
                         t0: float | None = None) -> None:
        """E0-6：辅助调用记账（单元外调用——shape/技能评审/分支摘要）。

        入任务账目（calls/usage/ts）+ trace `llm_call` 行（extra.aux_kind，
        供 cache_report trace 视角三分）；空段/异常不阻断（观测是辅佐）。
        防双计：这些调用发生在单元 usage 段之外（形状化在单元前、评审在收口、
        分支摘要在会话路径）。
        """
        from wuxing.usage_tracker import UsageTracker, trace_llm_call
        used = [u for u in (used or []) if isinstance(u, dict)]
        if not used:
            return
        if not hasattr(self, "_aux_calls") or self._aux_calls is None:
            self._aux_calls = []
        self._aux_calls.append({
            "kind": str(kind), "calls": len(used),
            "usage": UsageTracker.aggregate(used), "ts": time.time()})
        if getattr(self, "trace", None) is not None:
            try:
                latency = (time.perf_counter() - t0) * 1000 if t0 else 0.0
                trace_llm_call(self.trace, "", "", 0, latency, used,
                               extra={"aux_kind": str(kind)})
            except Exception as exc:
                logger.debug("辅助调用 trace 失败（观测不阻断）：%s", exc)

    def _merge_aux_into_metrics(self, metrics: dict) -> None:
        """E0-6：把「metrics 构建后」新增的辅助调用尾差并入任务 metrics（幂等）。

        技能评审在 _collect_metrics 之后运行——游标 `_aux_merged_upto` 防重合并；
        usage/cost/三分/归因同步校正；失败静默（观测不阻断）。
        """
        if not isinstance(metrics, dict):
            return
        aux = getattr(self, "_aux_calls", []) or []
        upto = int(getattr(self, "_aux_merged_upto", 0) or 0)
        new = aux[upto:]
        if not new:
            return
        calls = 0
        usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        kinds: dict = {}
        for a in new:
            n = int(a.get("calls") or 0)
            calls += n
            kind = str(a.get("kind") or "unknown")
            kinds[kind] = kinds.get(kind, 0) + n
            au = a.get("usage") or {}
            for k in usage:
                usage[k] += int(au.get(k) or 0)
        self._aux_merged_upto = len(aux)
        if not calls:
            return
        metrics["llm_calls"] = int(metrics.get("llm_calls") or 0) + calls
        mu = metrics.setdefault("usage", {})
        for k, v in usage.items():
            mu[k] = int(mu.get(k) or 0) + v
        for k in ("cache_miss", "reasoning_tokens"):
            vals = [(a.get("usage") or {}).get(k) for a in new]
            if any(v is not None for v in vals):
                mu[k] = int(mu.get(k) or 0) + sum(int(v or 0) for v in vals)
        from wuxing.usage_tracker import band_of
        cs = metrics.setdefault("ch_split", {
            "first": None, "continuation": None, "auxiliary": None,
            "miss_reasons": {}})
        prev = cs.get("auxiliary") or {
            "calls": 0, "prompt_tokens": 0, "cache_read_tokens": 0,
            "kinds": {}}
        prev["calls"] = int(prev.get("calls") or 0) + calls
        prev["prompt_tokens"] = (
            int(prev.get("prompt_tokens") or 0) + usage["input"])
        prev["cache_read_tokens"] = (
            int(prev.get("cache_read_tokens") or 0) + usage["cache_read"])
        ti, tc = prev["prompt_tokens"], prev["cache_read_tokens"]
        ratio = (tc / ti) if ti > 0 else None
        prev["ratio"] = ratio
        prev["band"] = band_of(ratio)
        pk = prev.setdefault("kinds", {})
        for k, n in kinds.items():
            pk[k] = int(pk.get(k) or 0) + n
        cs["auxiliary"] = prev
        mr = cs.setdefault("miss_reasons", {})
        mr["auxiliary"] = int(mr.get("auxiliary") or 0) + calls
        try:
            metrics.update(self._cost_metrics(metrics.get("usage") or {}))
        except Exception as exc:
            logger.debug("辅助账目成本校正失败（不阻断）：%s", exc)

    def _collect_metrics(self, units, snap: dict) -> dict:
        """P1 T4：任务级 metrics——llm 调用/usage 真值汇总 + 缓存命中统计。"""
        calls = 0
        usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        for u in units:
            calls += u.metrics.get("llm_calls", 0)
            uu = u.metrics.get("usage", {})
            for k in usage:
                usage[k] += uu.get(k, 0)
        # 可选真值（2026-09-11）：cache_miss / reasoning_tokens 不得在聚合层丢弃
        for k in ("cache_miss", "reasoning_tokens"):
            vals = [(u.metrics.get("usage", {}) or {}).get(k) for u in units]
            if any(v is not None for v in vals):
                usage[k] = sum(int(v or 0) for v in vals)
        # E0-6：CH 三分汇总（单元 ch_split + 辅助账目——账实一致）
        from wuxing.usage_tracker import band_of
        ch_split = {"first": None, "continuation": None, "auxiliary": None,
                    "miss_reasons": {}}

        def _acc(cat, src):
            if not src:
                return cat
            if cat is None:
                cat = {"calls": 0, "prompt_tokens": 0,
                       "cache_read_tokens": 0}
            for k in ("calls", "prompt_tokens", "cache_read_tokens"):
                cat[k] += int(src.get(k) or 0)
            return cat

        for u in units:
            cs_u = (u.metrics or {}).get("ch_split") or {}
            ch_split["first"] = _acc(ch_split["first"], cs_u.get("first"))
            ch_split["continuation"] = _acc(ch_split["continuation"],
                                            cs_u.get("continuation"))
            for k, n in (cs_u.get("miss_reasons") or {}).items():
                ch_split["miss_reasons"][k] = (
                    ch_split["miss_reasons"].get(k, 0) + int(n))
        aux = getattr(self, "_aux_calls", []) or []
        self._aux_merged_upto = len(aux)   # 技能评审晚于 metrics——尾差游标
        aux_cat = None
        if aux:
            aux_kinds: dict = {}
            _au = {"input": 0, "output": 0,
                   "cache_read": 0, "cache_write": 0}
            for a in aux:
                n = int(a.get("calls") or 0)
                kind = str(a.get("kind") or "unknown")
                aux_kinds[kind] = aux_kinds.get(kind, 0) + n
                au = a.get("usage") or {}
                for k in _au:
                    _au[k] += int(au.get(k) or 0)
            aux_total = sum(aux_kinds.values())
            if aux_total:
                calls += aux_total
                for k, v in _au.items():
                    usage[k] += v
                for k in ("cache_miss", "reasoning_tokens"):
                    vals = [(a.get("usage") or {}).get(k) for a in aux]
                    if any(v is not None for v in vals):
                        usage[k] = int(usage.get(k) or 0) + sum(
                            int(v or 0) for v in vals)
                ti, tc = _au["input"], _au["cache_read"]
                ratio = (tc / ti) if ti > 0 else None
                aux_cat = {"calls": aux_total, "prompt_tokens": ti,
                           "cache_read_tokens": tc, "ratio": ratio,
                           "band": band_of(ratio), "kinds": aux_kinds}
                ch_split["miss_reasons"]["auxiliary"] = (
                    ch_split["miss_reasons"].get("auxiliary", 0) + aux_total)
        for _name in ("first", "continuation"):
            c = ch_split[_name]
            if c:
                ti, tc = c["prompt_tokens"], c["cache_read_tokens"]
                ratio = (tc / ti) if ti > 0 else None
                c["ratio"] = ratio
                c["band"] = band_of(ratio)
        ch_split["auxiliary"] = aux_cat
        rc, sc = self.reply_cache, self.shape_cache
        # 命中率细分汇总（T2：语义命中质量/失效结构——诊断仪表）
        bd = {"semantic_hits": 0, "semantic_ok": 0,
              "first_round_misses": 0, "later_round_misses": 0}
        for u in units:
            for k in bd:
                bd[k] += u.metrics.get("cache_breakdown", {}).get(k, 0)
        # CH 口径（用户裁决 2026-10-02）：取所有单元中时间戳最新的「最近一次请求」
        latest_usage = None
        latest_ts = None
        for u in units:
            lu = (u.metrics or {}).get("usage_latest")
            ts = (u.metrics or {}).get("usage_latest_ts")
            if isinstance(lu, dict) and isinstance(ts, (int, float)) and (
                    latest_ts is None or ts > latest_ts):
                latest_usage, latest_ts = dict(lu), float(ts)
        return {
            "llm_calls": calls,
            "usage": usage,
            "usage_latest": latest_usage,
            "breakdown": bd,
            "ch_split": ch_split,
            "cache": {
                "reply": {"hits": rc.hits - snap["rh"],
                           "misses": rc.misses - snap["rm"],
                           "similar_hits": rc.similar_hits - snap["rs"]},
                "shape": {"hits": sc.hits - snap["sh"],
                           "misses": sc.misses - snap["sm"],
                           "similar_hits": sc.similar_hits - snap.get("ss", 0)},
            },
            **(self._fsc_metrics() or {}),
            **(self._cost_metrics(usage)),
        }

    @staticmethod
    def _cost_metrics(usage: dict) -> dict:
        """阶段 4（T4.1）：成本估算 + 缓存节省（reporting 单位真值聚合）。"""
        from wuxing.reporting import compute_usage_metrics, estimate_cost
        um = compute_usage_metrics(usage)
        return {"cost": {
            "estimate": round(estimate_cost(usage), 4),
            "save_tokens": um["save_tokens"],
            "save_cost": um["save_cost"],
            "cache_read_ratio": um["cache_read_ratio"],
        }}

    def _fsc_metrics(self) -> dict | None:
        """阶段 4（对齐项⑩）：FSC 健康指标——任务级差值 + 池内会话/覆盖率。"""
        pool = getattr(self, "session_pool", None)
        if pool is None:
            return None
        stats = pool.stats()
        base = getattr(self, "_pool_baseline", None) or {}

        def d(key: str) -> int:
            return int(stats.get(key, 0)) - int(base.get(key, 0))

        keyed, unkeyed = d("keyed"), d("unkeyed")
        total = keyed + unkeyed
        return {"fsc": {
            "reused": d("reused"),
            "matched": d("matched"),
            "audited": d("audited"),
            "switched": d("switched"),
            "evicted": d("evicted"),
            "keyed": keyed,
            "unkeyed": unkeyed,
            "sessions": int(stats.get("pool_size", 0)),
            "coverage": (keyed / total) if total > 0 else None,
        }}
