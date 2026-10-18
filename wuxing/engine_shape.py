"""Engine 形状化子系统（骨架分期 P4/F-3c：自 engine.py 提取的方法组 + 模块函数）。

来源：`wuxing/engine.py`（2026-10-06 迁移；方法体/函数体逐字节保持）。
理由：F-3 巨型文件分期——形状化/分割/路由面落隔离模块（S-2 mixin 裁定）；engine 只做类基接线。
依赖：经 `self` 访问引擎状态（cfg/llm/shape_cache/registry/trace）；**不得 import engine**（守卫）。
"""
import time

from wuxing.router import route_fragment

# P0-2 B（评估）：拆分质量观察指标——机械可算，不依赖模型自评。
_SHAPE_CONSTRUCTION_VERBS = ("编写", "撰写", "创建", "实现", "开发", "构建",
                             "生成", "新增", "添加")


def _shape_quality(frags: list) -> dict:
    """拆分质量指标：规模/域分布/文本重叠峰值/verify 构造信号（REAL-3 类）。"""
    frags = list(frags or [])
    domains: dict[str, int] = {}
    sets = []
    verify_construction = 0
    for f in frags:
        d = str(f.get("domain") or "")
        domains[d] = domains.get(d, 0) + 1
        t = str(f.get("text") or "")
        if d == "verify" and any(k in t for k in _SHAPE_CONSTRUCTION_VERBS):
            verify_construction += 1
        s = "".join(t.split())[:400]
        sets.append({s[i:i + 2] for i in range(max(0, len(s) - 1))})
    best = 0.0
    pair: list[str] = []
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            a, b = sets[i], sets[j]
            if not a or not b:
                continue
            jac = len(a & b) / len(a | b)
            if jac > best:
                best = jac
                pair = [str(frags[i].get("fragment_id")),
                        str(frags[j].get("fragment_id"))]
    return {"nodes": len(frags), "domain_dist": domains,
            "text_overlap_max": round(best, 3),
            "text_overlap_pair": pair,
            "verify_construction": verify_construction}


def _shape_quality_note(sq: dict) -> str:
    """拆分质量注记（报告可见——仅信号出现时；不阻断）。"""
    if not sq:
        return ""
    signals = []
    if float(sq.get("text_overlap_max") or 0) >= 0.6:
        pair = "×".join(str(x) for x in (sq.get("text_overlap_pair") or []))
        signals.append(f"文本重叠峰值 {sq.get('text_overlap_max')}（{pair}）")
    if int(sq.get("verify_construction") or 0) > 0:
        signals.append(f"verify 构造信号 {sq['verify_construction']} 个节点")
    if not signals:
        return ""
    dist = "/".join(f"{k}:{v}" for k, v in (sq.get("domain_dist") or {}).items())
    return ("[拆分质量] 节点 " + str(sq.get("nodes")) + f"（{dist}）；"
            + "；".join(signals) + "——留意职责重叠/域归属")


class EngineShapeMixin:
    def _build_fragments(self, task_text: str) -> list:
        """真实形态：golden_ratio 形状化（mock/真LLM）+ 分割 → Fragment → 域路由。

        B1 拆分（P13 审查行动项）：_shape_or_cached（形状化+缓存）/ _segment_to_frags（分割+路由）/
        _ensure_plan（补链）——单一职责。
        """
        from wuxing.usage_tracker import UsageTracker
        _ut = UsageTracker(self.llm)
        _t0 = time.perf_counter()
        _snap = _ut.snapshot()
        try:
            dag, shape, gr_llm = self._shape_or_cached(task_text)
            frags = self._segment_to_frags(dag, shape, gr_llm, task_text)
        finally:
            # E0-6：形状化+分割全过程 LLM 调用 → 辅助账目（缓存命中时为空）
            self._record_aux_call("shape", _ut.since(_snap), t0=_t0)
        self._ensure_plan(frags, task_text)
        # P8.1 条件域语义扫描：user 专用短语命中 → 激活 user 域 → 重路由
        self._sync_conditional_domains(frags)
        # P1-2（用户裁决 Q1=B）：拆分 lint——机械校验 + 防御性处置（失败不阻断）
        _lint_note = ""
        try:
            from wuxing.shape_lint import apply_shape_lint
            frags, _lint, _lint_note = apply_shape_lint(frags)
            if self.trace is not None and (
                    _lint.get("reroute_ids") or _lint.get("dangling")
                    or _lint.get("deliverable_overlaps")
                    or _lint.get("verify_anchored")
                    or int(_lint.get("components") or 0) > 1):
                self.trace.log(
                    "shape_lint", "", "",
                    rerouted=",".join(_lint.get("reroute_ids") or []),
                    deps_stripped=len(_lint.get("dangling") or {}),
                    deliverable_overlaps=len(
                        _lint.get("deliverable_overlaps") or []),
                    overlaps_serialized=len(
                        _lint.get("overlap_serialized") or []),
                    verify_anchored=len(_lint.get("verify_anchored") or {}),
                    components=int(_lint.get("components") or 0),
                    no_execute=bool(_lint.get("no_execute")))
        except Exception:
            _lint_note = ""
        # P0-2 B（评估）：拆分质量观察（trace + 报告注记——不阻断；lint 修复后度量）
        try:
            _sq = _shape_quality(frags)
            if self.trace is not None:
                self.trace.log("shape_quality", "", "", **_sq)
            self._shape_quality_note = _shape_quality_note(_sq)
        except Exception:
            self._shape_quality_note = ""
        if _lint_note:
            self._shape_quality_note = (
                _lint_note + ("\n\n" + self._shape_quality_note
                              if self._shape_quality_note else ""))
        return frags

    def _default_shape_llm(self):
        """默认模型的形状化客户端（2026-09-19 用户裁决：非域级、非供应商专用）。

        解析 cfg.llm（含 providers 引用）→ 凭据可用（env > 凭据存储）→ 适配引擎
        默认 provider；mock/未配置/无凭据/构造失败 → None（调用方降级 mock 并提示）。
        """
        spec = getattr(self.cfg, "llm", None)
        if not spec or str(spec).strip().lower() == "mock":
            return None
        try:
            from wuxing.llm.factory import resolve_api_key_for
            if not resolve_api_key_for(spec, getattr(self.cfg, "providers", None),
                                       allow_stored_credentials=not self.isolated):
                return None
            provider = getattr(self, "llm", None)
            if provider is None or type(provider).__name__ == "MockLlmProvider":
                return None
            from wuxing.llm.shape_adapter import DefaultModelShapeLlm
            return DefaultModelShapeLlm(provider, model_name=str(spec))
        except Exception:
            # 形状化模型不可用（凭据/构造失败）→ None（调用方降级 mock）
            return None

    def _shape_or_cached(self, task_text):
        """形状化 + 缓存（P9 R2）：命中直接取 DAG，未命中调用后写缓存。

        2026-09-18（用户裁决）：真实形状化默认开；无凭据 → mock 降级 +
        引导提示（_shape_notice）；降级结果不写缓存（配好凭据后可重跑真实形状化）。
        """
        from golden_ratio.calibrate import build_dag
        from golden_ratio.config import AlgorithmConfig
        from golden_ratio.difficulty import compute_shape
        from golden_ratio.llm import MockLLM as GrMockLLM
        cached = self.shape_cache.get(task_text) if hasattr(self, "shape_cache") else None
        if cached is None and hasattr(self, "shape_cache") \
                and self.shape_cache.similar_threshold > 0:
            # P1 T3：形状化语义复用（标点/空白微漂移——真 LLM 形状化昂贵，免调用）
            cached, _sim = self.shape_cache.similar_get(task_text)
        if cached:
            dag = build_dag(cached)
            return dag, compute_shape(dag, AlgorithmConfig()), GrMockLLM()
        fallback_mock = False
        if self.cfg.use_real_shape:
            gr_llm = self._default_shape_llm()
            if gr_llm is None:
                self._shape_notice = (
                    "[形状化提示] 真实形状化已开启，但默认模型不可用"
                    "（未选择模型或缺少凭据）——本次使用 mock 形状化。\n"
                    "配置：设置 → 模型与供应商（选择默认模型并保存其密钥）；\n"
                    "关闭本机制：设置 → 机制调优 → 真实形状化。"
                    "（形状化使用默认模型，与域级路由无关）")
                gr_llm = GrMockLLM()
                fallback_mock = True
        else:
            gr_llm = GrMockLLM()
        from golden_ratio.shape import shape_task
        dag, shape = shape_task(task_text, gr_llm)
        if hasattr(self, "shape_cache") and not fallback_mock:
            self.shape_cache.put(task_text, {
                "nodes": [{"id": n.id, "text": n.text,
                            "domain": dict(n.domain_dist),
                            "trades": list(n.trades),
                            "complexity": n.complexity,
                            "deliverable": n.deliverable,
                            "weight": n.color_weight}
                           for n in dag.nodes],
                "edges": [[a, b] for a, b in dag.edges],
            })
        return dag, shape, gr_llm

    def _segment_to_frags(self, dag, shape, gr_llm, task_text) -> list:
        """分割 + 域路由：Fragment → dict 列表（B1 拆分）。"""
        from golden_ratio.segment import segment
        frags_gr = segment(dag, shape, gr_llm)
        frags = []
        for f in frags_gr:
            texts = " ".join(n.text for n in dag.nodes if n.id in f.node_ids)
            frags.append({
                "fragment_id": f.fragment_id,
                "domain": route_fragment(texts),
                "deps": list(f.upstream),
                "text": texts,
                # 智脑分级（三级参照表）：碎片粒度占比（segment size / shape total）
                "granularity": round(f.size / shape.total_size, 4)
                if getattr(shape, "total_size", 0) else None,
                # L4 真跑发现：交付物语义（模型未知交付类型→探索不止）
                "deliverables": sorted(set(f.deliverables)),
            })
        return frags

    def _ensure_plan(self, frags: list, task_text: str):
        """plan 补链（规划总是需要——不机械补 verify，语义命中才启用）。"""
        domains = {x["domain"] for x in frags}
        if "plan" not in domains:
            frags.insert(0, {"fragment_id": "F-plan0", "domain": "plan",
                             "deps": [], "text": task_text, "_forced": True})

    def _sync_conditional_domains(self, frags: list):
        """P8.1：条件域激活 + 重路由（命中未启用条件域 → 回退语义域）。"""
        # 扫描：原始语义命中（不带 active）——条件域命中 → 激活
        for f in frags:
            raw_d = route_fragment(f["text"])
            if self.registry.is_conditional(raw_d):
                self.registry.activate([raw_d])
        # 重路由（带启用集）；_forced 碎片（引擎决策）不被覆盖
        active = set(self.registry.active_ids())
        for f in frags:
            if f.get("_forced"):
                continue
            f["domain"] = route_fragment(f["text"], active=active)
