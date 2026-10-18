"""DAG 编排（Q4：按 Fragment 依赖图调度，无依赖并行——P16 多手并行落地）。

原始构想（用户）：LLM 多出几双手，每双手少拿一些东西，同时处理任务——
不增加成本（调用数不变）增快效率（墙钟时间按依赖链摊薄）。
P1 串行简化 → P16 并行改造：就绪集（deps 满足）并发执行（max_parallel_units）；
每碎片独立 Runner 实例（独立会话上下文——Q3 双层混合）；三处锁（workspace/cache/ledger）。
"""
import logging
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from wuxing import confirm_copy
from wuxing.events import (
    ArtifactWritten,
    FscAudit,
    FscSwitch,
    UnitAutoRetry,
    UnitDone,
    UnitNeedsConfirm,
    UnitStarted,
)
from wuxing.protocols import UnitResult

logger = logging.getLogger(__name__)

# #2（用户裁决 2026-09-11）：并行硬上限 10（目标 8——Cursor 参考，机制特殊略缩）
MAX_PARALLEL_UNITS = 10

# G（2026-09-11 报告 #6）：注入上限按域——verify 验收对象必须完整
# （planner「正文被截断」类拒绝的根因是 800 字符注入）；其余域维持 800
_INJECT_MAX = {"verify": 8000}

# P0-1 D（评估方向）：verify 验收对象定位——manifest 中「摘要/结果类」产物
# 不是交付物本体；真实代码/数据文件才是（REAL-15/T-2 误杀根因）。
# kind="" 保留（模型自写文件未声明 kind——可能是真交付物，宁覆盖勿遗漏）。
_SUMMARY_KINDS = {"plan", "result", "verdict", "acceptance", "design"}
_INTERNAL_PATHS = {"task_state.json", "manifest.json", "brain_memory.json"}


def _real_deliverable_index(ws, limit: int = 10) -> list[tuple[str, str]]:
    """工作区真实交付物索引（manifest 非摘要类）→ [(path, kind)]（新→旧，去重）。"""
    out: list[tuple[str, str]] = []
    try:
        items = list(ws.manifest() or [])
    except Exception:  # 索引是辅助设施，失败不阻断
        return out
    for a in reversed(items):
        p = str(getattr(a, "path", "") or "")
        k = str(getattr(a, "kind", "") or "")
        if not p or k in _SUMMARY_KINDS:
            continue
        if p.startswith(".wuxing/") or "/.wuxing/" in p:
            continue
        if p in _INTERNAL_PATHS or any(p == x[0] for x in out):
            continue
        out.append((p, k))
        if len(out) >= limit:
            break
    return out


class Orchestrator:
    def __init__(self, cfg, registry, workspace, llm, tools, llm_for=None,
                 llm_candidate_count=None,
                 confirm_gate=None, auto_confirm=True, reply_cache=None,
                 brain_memory=None, provenance=None, skills=None, shared=None,
                 trace=None, file_cache=None, conversation=None,
                 session_pool=None, ext_segments=None,
                 skills_disabled=None, hook_collect=None, state_root=None):
        self.cfg = cfg
        self.confirm_gate = confirm_gate
        self.registry = registry
        self.ws = workspace
        # E3-1/R5（T2）：状态根（会话存档/上下文来源等账本→state_root；缺省=ws.root）
        self.state_root = (pathlib.Path(state_root) if state_root
                           else workspace.root)
        self.llm = llm
        self.tools = tools
        self.llm_for = llm_for
        self.llm_candidate_count = llm_candidate_count  # S1-A/L2：(domain)->候选数
        self.auto_confirm = auto_confirm
        self.reply_cache = reply_cache
        self.brain_memory = brain_memory
        self.provenance = provenance
        self.skills = skills  # SK：SkillRegistry（透传 Runner——渐进披露）
        self.shared = shared  # L3：任务级共享区（透传 Runner——碎片间协作）
        self.trace = trace  # L1-1：trace（透传 Runner——每碎片同写一文件，锁互斥）
        self.file_cache = file_cache  # B5（审查）：L1 产物内容缓存（依赖注入免重复 IO）
        self.conversation = conversation  # B 模式：会话历史段（透传 Runner）
        self.session_pool = session_pool  # FSC（2026-09-11）：跨轮会话延续池
        self.ext_segments = list(ext_segments or ())  # E2-1：扩展提示词段
        self.skills_disabled = set(skills_disabled or ())  # E2-4：预设技能禁用
        # E3-2（P1）：钩子收集器（Engine 注入 dispatcher.dispatch_collect）
        self.hook_collect = hook_collect
        self._task_round = 0  # FSC 轮次计数（每次 run 一次任务轮）
        # 保留单 Runner（兼容：engine.confirm_unit 单单位路径）——并发路径用 _make_runner 工厂
        self.runner = self._make_runner()
        self.runner.emit_event = None  # 由 run() 注入事件发射器

    def _make_runner(self):
        """P16：每碎片独立 Runner（独立会话状态——并发安全前提）。"""
        from wuxing.runner import Runner
        return Runner(self.cfg, self.registry, self.ws, self.llm, self.tools,
                      llm_for=self.llm_for, confirm_gate=self.confirm_gate,
                      auto_confirm=self.auto_confirm, reply_cache=self.reply_cache,
                      brain_memory=self.brain_memory, provenance=self.provenance,
                      skills=self.skills, shared=self.shared, trace=self.trace,
                      conversation=self.conversation,
                      ext_segments=self.ext_segments,
                      skills_disabled=self.skills_disabled,
                      hook_collect=self.hook_collect,
                      state_root=self.state_root)

    def run(self, fragments: list, task_text: str, on_event=None,
            seed_done: dict | set | None = None,
            resume_sessions: dict | None = None,
            cancel=None, references_text: str = "") -> list:
        """fragments: [{"fragment_id","domain","deps"}] → [UnitResult]

        P16 并行：就绪集并发（max_parallel_units）；依赖链保持拓扑序；
        on_event: 可选回调（P3 事件流）。
        seed_done: 已完成单位集（P6 resume——依赖满足条件）。
          - dict：完整 UnitResult（带 artifacts——P0 T5 恢复链：下游需读产物内容）
          - set：兼容旧语义（空壳——依赖满足而已）
        resume_sessions: P4 T3 消息级断点 {fragment_id: [messages]}——存续跑。
        """
        def emit(e):
            if on_event:
                on_event(e)
        self._task_round += 1  # FSC：任务轮序号（保留轮龄判据）
        # 重大优化清单 #2：确认卡位置感（共 N 步 / 第 i 步——按任务计划顺序）
        self._frag_positions = {
            str(f.get("fragment_id", "")): (i + 1, len(fragments))
            for i, f in enumerate(fragments)}
        if isinstance(seed_done, dict):
            done = dict(seed_done)
        else:
            done = {uid: UnitResult(unit_id=uid, domain_id="", status="ok")
                    for uid in (seed_done or set())}
        results = []
        remaining = list(fragments)
        # L4/GLM 差分发现：plan 域碎片隐式全局前置——计划是全任务依赖；
        # 两阶段调度：plan 阶段（内部并行——P16 多手）→ 其他域阶段（等计划产物注入）
        plan_frags = [f for f in remaining if f.get("domain") == "plan"]
        other_frags = [f for f in remaining if f.get("domain") != "plan"]
        # B8（审查）：统一调度函数——原 _schedule_stage 与主 while 复制粘贴
        # （且 _schedule_stage 的 other_frags 参数从未使用——漂移风险）
        # 2026-09-11 修复（真实测试暴露）：plan 碎片依赖其他域时，plan 阶段
        # 无就绪 → 以前被误判 cycle 判死；修复：defer 到第二阶段调度
        results, done, deferred = self._schedule(
            plan_frags, task_text, emit, done, results, resume_sessions,
            defer=True, cancel=cancel, references_text=references_text)
        rest = list(other_frags) + list(deferred)
        if self.session_pool is not None and rest:
            # C 全形态（A 阶段）：plan 工作流标签 → 碎片继承（工作流键）
            self._inject_plan_labels(rest, results, done)
        results, done, _ = self._schedule(
            rest, task_text, emit, done, results, resume_sessions,
            cancel=cancel, references_text=references_text)
        # 乱序完成 → 按输入碎片顺序聚合（报告/状态稳定）
        order = {f["fragment_id"]: i for i, f in enumerate(fragments)}
        results.sort(key=lambda r: order.get(r.unit_id, 0))
        return results

    def _inject_plan_labels(self, frags: list, results: list,
                            done: dict | None = None) -> None:
        """C 全形态（A 阶段）：plan 输出的『工作流：xxx』标签注入碎片。

        旁路字段 _fsc_labels（仅并入工作流键——不改 prompt，保持 FSC on/off
        对照纯净）。plan 文本源：单元 logs（LLM 文本）+ 产物内容（限 20000
        字符）。仅 FSC 启用时由 run() 调用。
        """
        from wuxing.session_pool import assign_tags, extract_tag_contexts
        units = [u for u in list(results) + list((done or {}).values())
                 if getattr(u, "domain_id", "") == "plan"]
        texts = []
        for u in units:
            texts.extend(str(x) for x in (getattr(u, "logs", None) or []))
            for p in (list(getattr(u, "deliverables", None) or [])
                      + [a.path for a in (getattr(u, "artifacts", None) or [])]):
                c = self._read(p)
                if c:
                    texts.append(c[:20000])
        if not texts or not frags:
            return
        items = extract_tag_contexts("\n".join(texts))
        if not items:
            return
        mapping = assign_tags(frags, items)
        for frag in frags:
            tags = mapping.get(frag.get("fragment_id")) or []
            if tags:
                frag["_fsc_labels"] = tags

    @staticmethod
    def _parallel_limit(cfg) -> int:
        """并行度收敛（#2）：下限 1、硬上限 MAX_PARALLEL_UNITS（10）。"""
        try:
            val = int(getattr(cfg, "max_parallel_units", 8))
        except (TypeError, ValueError):
            val = 8
        return max(1, min(val, MAX_PARALLEL_UNITS))

    def _schedule(self, frags: list, task_text: str, emit, done: dict,
                  results: list, resume_sessions, defer: bool = False,
                  cancel=None, references_text: str = "") -> tuple:
        """就绪集调度（串行保序/并行多手）——单实现，两阶段共用（B8）。

        defer=True：本阶段无就绪碎片时不判失败，返回未解决集（跨阶段依赖
        延后到下一阶段——2026-09-11 真实测试修复：plan 依赖其他域被误判环）；
        defer=False：无就绪 = 真环/依赖缺失 → 标记 failed（不阻塞其他碎片）。
        返回 (results, done, unresolved)。
        """
        remaining = list(frags)
        limit = self._parallel_limit(self.cfg)
        while remaining:
            if cancel is not None and cancel.is_set():
                # 壳 P1 对齐项②：取消——剩余碎片全部记 cancelled（不再调度）
                for frag in remaining:
                    res = UnitResult(unit_id=frag["fragment_id"],
                                     domain_id=frag["domain"],
                                     status="cancelled",
                                     error="cancelled by user")
                    results.append(res)
                    done[frag["fragment_id"]] = res
                break
            def _dep_ready(frag: dict) -> bool:
                """真测裁决 W3：挂起不满足依赖（挂起=DAG 调度一等状态）；
                require_ok_deps（票据）额外要求依赖验收通过（ok 且非 verdict_fail）。"""
                for d in frag["deps"]:
                    u = done.get(d)
                    if u is None:
                        return False
                    if str(getattr(u, "status", "")) in ("needs_confirm",
                                                            "needs_answer"):
                        return False
                    if frag.get("require_ok_deps") and (
                            getattr(u, "status", "") != "ok"
                            or getattr(u, "verdict_fail", False)):
                        return False
                return True
            ready = [f for f in remaining if _dep_ready(f)]
            if not ready:
                if defer:
                    return results, done, remaining
                blocked_by_pending = any(
                    any(str(getattr(done.get(d), "status", "")) in
                        ("needs_confirm", "needs_answer")
                        for d in f["deps"]) for f in remaining)
                if blocked_by_pending:
                    # 挂起导致的下游等待：保留待续（确认后由引擎续跑），不判失败
                    return results, done, remaining
                # 死锁/坏依赖：跳过并标记 failed（不阻塞其他）
                for frag in remaining:
                    results.append(UnitResult(unit_id=frag["fragment_id"],
                                              domain_id=frag["domain"],
                                              status="failed",
                                              error="orchestrator: unsatisfied deps (cycle)"))
                break
            if limit <= 1 or len(ready) == 1:
                for frag in ready:
                    # A2 修复（2026-09-11 审查）：提交前对 done 快照——当前单元
                    # 执行期间后续单元完成会修改共享 done；worker 迭代 done.values()
                    # 时字典变更 → RuntimeError（并行批次由其突出）
                    res = self._run_one(frag, task_text, emit, dict(done),
                                        (resume_sessions or {}).get(
                                            frag["fragment_id"]),
                                        cancel=cancel,
                                        references_text=references_text)
                    results.append(res)
                    done[frag["fragment_id"]] = res
                    remaining.remove(frag)
            else:
                workers = min(limit, len(ready))
                # A2 修复：批次快照在提交前（无并发修改）——就绪集内互相无依赖
                # （deps 已全部在 done），快照语义等价且消除跨线程迭代竞态
                batch_done = dict(done)
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = {ex.submit(self._run_one, frag, task_text, emit,
                                      batch_done,
                                      (resume_sessions or {}).get(
                                          frag["fragment_id"]),
                                      cancel,
                                      references_text=references_text): frag
                            for frag in ready}
                    for fut in as_completed(futs):
                        frag = futs[fut]
                        res = fut.result()
                        results.append(res)
                        done[frag["fragment_id"]] = res
                        remaining.remove(frag)
        return results, done, []

    def _read(self, path: str) -> str | None:
        """B5（审查）：产物内容统一读入口——file_cache 优先（进程内免重复 IO），
        未接缓存回退 ws.read（存在性/逃逸语义一致——FileCache miss 时读盘）。
        注意：路径解析必须经 ws（workspace 相对语义）——FileCache 只做内存缓存。
        """
        if self.file_cache is not None:
            c = self.file_cache.get(path)
            if c is not None:
                return c
        content = self.ws.read(path)
        if content is not None and self.file_cache is not None:
            self.file_cache.put(path, content)
        return content

    def _inject_single(self, path: str, frag: dict, u, plan_text: str,
                       result_text: str, paths: list, max_len: int) -> tuple:
        """注入单个产物（内容+路径）到对应字段（S-C 共享注入逻辑）。

        真测 REAL-13(b)：空产物（如空 result）不注入幽灵条目——避免下游只看到
        路径没有正文而误判「产物缺失」。
        """
        if path in paths:
            return plan_text, result_text, paths
        content = self._read(path)
        if content is None or not content.strip():
            return plan_text, result_text, paths
        paths.append(path)
        if len(content) > max_len:
            content = content[:max_len] + "…"
        if frag.get("domain") == "verify":
            result_text = f"{result_text}\n{content}" if result_text else content
        elif u.domain_id == "plan" and frag.get("domain") == "execute":
            plan_text = f"{plan_text}\n{content}" if plan_text else content
        else:
            result_text = f"{result_text}\n{content}" if result_text else content
        return plan_text, result_text, paths

    def _confirm_impact(self, frag: dict) -> dict:
        """确认门影响清单（M7 #7 · A2）：工具白名单/交付类型/依赖碎片/摘要。

        数据源均在位：域定义 tool_whitelist（registry）+ 碎片元数据（deps/deliverables）。
        """
        tools: list = []
        try:
            reg = getattr(self.confirm_gate, "registry", None)
            if reg is not None:
                defn = reg.get(str(frag.get("domain", "")))
                tools = [str(t) for t in (getattr(defn, "tool_whitelist", ()) or ())]
        except Exception:
            tools = []
        return {
            "tools": tools,
            "deliverables": [str(d) for d in (frag.get("deliverables") or [])],
            "depends": [str(d) for d in (frag.get("deps") or [])],
            "summary": str(frag.get("text", ""))[:160],
        }

    def _confirm_view(self, frag: dict, trigger: str,
                      position: tuple | None = None) -> dict:
        """确认卡四要素视图（A′：机制侧结构化——壳侧统一渲染）。"""
        if position is None:
            position = getattr(self, "_frag_positions", {}).get(
                str(frag.get("fragment_id", "")), (None, None))
        index, total = position if position else (None, None)
        return confirm_copy.unit_confirm_view(
            impact=self._confirm_impact(frag), trigger=trigger,
            index=index, total=total)

    def _dep_context(self, done: dict, frag: dict,
                     max_len: int | None = None) -> tuple:
        """P0 参数接线（S4）+ 冒烟修复：依赖产物【内容+路径】按【当前域】注入。

        max_len=None → 按域默认（verify 8000 / 其余 800——G）。

        冒烟实证：verify 只收内容不收路径 → 盲猜路径 read not found →
        "只在勘察" → budget 耗尽（契约无收敛指令）。修正：paths 参数 = 依赖产物路径。
        """
        if max_len is None:
            max_len = _INJECT_MAX.get(frag.get("domain"), 800)
        plan_text, result_text, paths = "", "", []
        for dep in frag.get("deps", []):
            u = done.get(dep)
            if u is None:
                continue
            # S-C：真实交付物优先（写工具实际写出的文件——验收对象是物不是叙述）
            # 真测 REAL-13(b)：空内容产物跳过（继续注入其它真实产物）
            real = [p for p in getattr(u, "deliverables", [])
                    if p and (self._read(p) or "").strip()]
            if real:
                for p in real[:2]:
                    plan_text, result_text, paths = self._inject_single(
                        p, frag, u, plan_text, result_text, paths, max_len)
                continue
            # 回退：契约产物（叙述文本）
            for a in (u.artifacts or [])[:1]:
                plan_text, result_text, paths = self._inject_single(
                    a.path, frag, u, plan_text, result_text, paths, max_len)
        # L4 真跑发现：计划产物全局注入——计划是任务级上下文（无依赖的分析型
        # 碎片无路径提示 → 模型 ls 探索 3 轮——注入即免探索）
        for u in done.values():
            if u.domain_id != "plan" or u.status != "ok" or u.unit_id in frag.get("deps", []):
                continue
            real = [p for p in getattr(u, "deliverables", [])
                    if p and (self._read(p) or "").strip()]
            cand = real[:1] or [a.path for a in (u.artifacts or [])][:1]
            for p in cand:
                plan_text, result_text, paths = self._inject_single(
                    p, frag, u, plan_text, result_text, paths, max_len)
        # P0-1 D（评估方向）：verify 验收对象定位——附「工作区真实交付物索引」
        # （依赖注入可能只有摘要/结果文档；真实代码/数据在工作区——给可读路径）
        # O2-3：条件扩展 verify → ("verify", "user")——user 体验审查同样
        # 需要真实交付物视野（防盲猜路径）
        if frag.get("domain") in ("verify", "user"):
            idx = [(p, k) for p, k in _real_deliverable_index(self.ws)
                   if p not in paths]
            if idx:
                head = ("[工作区交付物索引] 以下真实交付物可用 read_file 读取"
                        "（验收对象以文件正文为准；摘要/结果文档仅作索引）：")
                lines = [head]
                lines += [f"- {p}（{k}）" for p, k in idx]
                block = "\n".join(lines)
                result_text = f"{result_text}\n{block}" if result_text else block
        return plan_text, result_text, "\n".join(paths)

    def _run_one(self, frag: dict, task_text: str, emit, done: dict,
                 resume_session: list | None = None,
                 cancel=None, references_text: str = "") -> UnitResult:
        """S1-A：自动恢复环——attempts 仅计一次；provider 类失败有界重试/降级。

        每候选 = 1 次初跑 + provider_retry_max 次同候选重试；候选序来自
        llm_candidate_count（缺省 1——零行为变化）；不占 fragment_max_attempts。
        """
        frag["attempts"] = int(frag.get("attempts") or 0) + 1
        retry_cap = max(0, int(getattr(self.cfg, "provider_retry_max", 1) or 0))
        backoff = max(0.0, float(
            getattr(self.cfg, "provider_retry_backoff_s", 15.0) or 0.0))
        n_cand = (int(self.llm_candidate_count(frag["domain"]))
                  if self.llm_candidate_count is not None else 1)
        retry, candidate = 0, 0
        while True:
            res = self._attempt_unit(frag, task_text, emit, done, resume_session,
                                     cancel, references_text,
                                     candidate_index=candidate,
                                     emit_started=(retry == 0 and candidate == 0))
            if getattr(res, "failure_class", "") != "provider":
                return res
            if cancel is not None and cancel.is_set():
                return res
            if retry < retry_cap:
                retry += 1
                self._note_auto_retry(emit, frag, kind="retry", attempt=retry,
                                      candidate=candidate,
                                      model=self._candidate_name(frag, candidate))
                if backoff > 0:
                    time.sleep(backoff)
                continue
            if candidate + 1 < n_cand:
                candidate += 1
                retry = 0
                self._note_auto_retry(emit, frag, kind="fallback", attempt=0,
                                      candidate=candidate,
                                      model=self._candidate_name(frag, candidate))
                continue
            return res

    def _note_auto_retry(self, emit, frag, kind, attempt, candidate, model=""):
        """S1-A：自动恢复记账（trace 审计 + 壳可见事件；失败不阻断）。"""
        if self.trace is not None:
            self.trace.log(
                "provider_fallback" if kind == "fallback" else "provider_retry",
                frag["fragment_id"], frag["domain"],
                kind=kind, attempt=attempt, candidate=candidate, model=model)
        try:
            emit(UnitAutoRetry(unit_id=frag["fragment_id"],
                               domain_id=frag["domain"], kind=kind,
                               attempt=attempt, candidate=candidate,
                               model=model))
        except Exception as exc:
            logger.debug("自动恢复事件发送失败（不阻断）：%s", exc)

    def _candidate_name(self, frag, candidate: int) -> str:
        """候选 provider 名（仅展示用；解析失败返回空——不阻断）。"""
        if self.llm_for is None:
            return ""
        try:
            p = self.llm_for(frag["domain"], frag.get("text"), candidate)
            return str(p.name()) if hasattr(p, "name") else ""
        except Exception:
            # 仅展示用（候选名解析失败不阻断任务）
            return ""

    def _attempt_unit(self, frag: dict, task_text: str, emit, done: dict,
                      resume_session: list | None = None,
                      cancel=None, references_text: str = "",
                      candidate_index: int = 0,
                      emit_started: bool = True) -> UnitResult:
        """单次尝试（并发 worker 体；done 只读——依赖已满足才进就绪集）。"""
        if cancel is not None and cancel.is_set():
            # 壳 P1 对齐项②：已提交的 worker 也不得再开跑（取消优先）
            return UnitResult(unit_id=frag["fragment_id"],
                              domain_id=frag["domain"], status="cancelled",
                              error="cancelled by user")
        runner = self._make_runner()
        runner.emit_event = emit  # P4 T1：状态机事件注入（原死属性接线）
        plan_text, result_text, paths_str = self._dep_context(done, frag)
        params = {
            "goal": frag.get("text", task_text),
            "task": task_text,
            "references": references_text,   # 阶段 5（⑧）：任务级参考文件
            "plan": plan_text,
            "result": result_text,
            "paths": paths_str,
            "granularity": frag.get("granularity"),
            "fragment_key": frag.get("text", task_text),
            # L4 真跑发现：交付物语义注入（模型未知交付类型→探索不止）
            "deliverables": frag.get("deliverables") or [],
        }
        # FSC（2026-09-11 设计）：匹配→同键锁→执行→retain；窗口机制（审计/切换）
        # B2（六轮审查）：延续段全程受 try 保护——match/审计/trace 异常也必须
        # 释放同键锁（原实现锁在 try 外获取——异常即永久占锁）
        # A1（2026-09-22）：来源开关——prefix=false 不匹配也不 retain
        from wuxing.context_sources import resolve as _resolve_sources
        _conv_name = ""
        try:
            _conv = getattr(self, "conversation", None)
            if _conv is not None:
                _conv_name = _conv.path.name
        except AttributeError:
            _conv_name = ""
        _src = _resolve_sources(
            self.state_root, conversation=_conv_name, unit=frag["fragment_id"],
            default_budget=int(getattr(self.cfg, "context_budget_tokens", 0) or 0))
        key = lock = cont = None
        cont_msgs = None
        started = False
        locked = False
        if _src["prefix"] and self.session_pool is not None:
            from wuxing.session_pool import fsc_key
            # C 通道（A 阶段）：标签旁路注入——只并入键源（不改 prompt）
            _lbl = " ".join(f"工作流：{t}" for t in (frag.get("_fsc_labels") or []))
            _key_src = frag.get("text", "") + (("\n" + _lbl) if _lbl else "")
            key = fsc_key(frag["domain"], _key_src, paths_str)
            self.session_pool.note_fragment(key is not None)  # A2 覆盖率口径
        try:
            if self.session_pool is not None and key is not None:
                lock = self.session_pool.key_lock(key)
                lock.acquire()  # 同键串行（会话安全）；异键不受影响
                locked = True
                cont = self.session_pool.match(frag["domain"], key,
                                               self._task_round)
                switch_ratio = None
                for ev in self.session_pool.drain_events():
                    if (ev.get("event") == "session_switched"
                            and ev.get("key") == key):
                        switch_ratio = ev.get("ratio")   # 阶段 4（⑩）：切换事件透出
                    if self.trace is not None:
                        # B3（六轮审查）：用事件自身键（事件可能被其它键的
                        # 单元 drain——用当前单位键会错配归属）
                        ev_key = ev.get("key") or key
                        self.trace.log(ev["event"], frag["fragment_id"],
                                       frag["domain"],
                                       key="|".join(sorted(ev_key[1])),
                                       ratio=ev.get("ratio"))
                if cont is not None:
                    cont_msgs = [dict(m) for m in cont.messages]
                    # A2（2026-09-22）：碎片消息三键裁剪（投影层；池/存档零改写）
                    from wuxing.context_edits import apply_unit_edits
                    from wuxing.context_sources import load_unit_edits
                    _edits = load_unit_edits(self.state_root, frag["fragment_id"])
                    if _edits:
                        cont_msgs, _skipped = apply_unit_edits(cont_msgs, _edits)
                        if self.trace is not None:
                            if _skipped:
                                self.trace.log("context_edit_skipped",
                                               frag["fragment_id"],
                                               frag["domain"],
                                               reason="fp_mismatch",
                                               count=len(_skipped))
                            if len(_skipped) < len(_edits):
                                self.trace.log("context_edit_applied",
                                               frag["fragment_id"],
                                               frag["domain"],
                                               applied=len(_edits) - len(_skipped))
                    if getattr(cont, "audit_pending", False):
                        # 60%：严格审查（方案 A——机制指令自查，一次）
                        w = max(1, self.session_pool.context_window)
                        cont_msgs.append({
                            "role": "user",
                            "content": f"[会话审计] 本会话已使用约 "
                                       f"{int(cont.chars / w * 100)}% 上下文——"
                                       f"请核对已有结论与产物的一致性，"
                                       f"确认无误后再继续。"})
                        self.session_pool.mark_audited(key)
                        emit(FscAudit(unit_id=frag["fragment_id"],
                                      domain_id=frag["domain"],
                                      ratio=round(cont.chars / w, 3)))
                        if self.trace is not None:
                            self.trace.log("session_audit", frag["fragment_id"],
                                           frag["domain"],
                                           key="|".join(sorted(key[1])))
                elif self.session_pool.consume_switched(key):
                    # 阶段 4（⑩）：切换事件透出（auto_confirm 下同样可见）
                    emit(FscSwitch(unit_id=frag["fragment_id"],
                                   domain_id=frag["domain"],
                                   ratio=switch_ratio or 0.0))
                    if not self.auto_confirm:
                        # B4（六轮审查）：80% 切换需用户确认（设计 §4）——挂起该单元；
                        # 批准后续跑（新会话——旧会话已归档，匹配自然走新会话）
                        emit(UnitNeedsConfirm(unit_id=frag["fragment_id"],
                                              domain_id=frag["domain"],
                                              reason="会话窗口切换待确认",
                                              view=self._confirm_view(
                                                  frag, "session_switch"),
                                              impact=self._confirm_impact(frag)))
                        return UnitResult(unit_id=frag["fragment_id"],
                                          domain_id=frag["domain"],
                                          status="needs_confirm",
                                          error="confirm: 会话上下文窗口达到切换阈值")
            if emit_started:
                emit(UnitStarted(unit_id=frag["fragment_id"],
                                 domain_id=frag["domain"]))
            started = True
            res = runner.run_unit(frag["fragment_id"], frag["domain"], params,
                                  resume_session=resume_session,
                                  continue_from=cont_msgs,
                                  cancel=cancel,
                                  llm_candidate=candidate_index)
        finally:
            if _src["prefix"] and self.session_pool is not None and key is not None:
                if started:
                    try:
                        rec = self.session_pool.retain(
                            key, frag["domain"], getattr(runner, "_messages", []),
                            unit_id=frag["fragment_id"],
                            current_round=self._task_round, reused=cont is not None)
                        if self.trace is not None:
                            self.trace.log(
                                "session_reused" if cont is not None
                                else "session_created",
                                frag["fragment_id"], frag["domain"],
                                key="|".join(sorted(key[1])),
                                session_chars=(rec.chars if rec else 0),
                                reuse=(rec.reuse if rec else 0),
                                **({"session_src": cont.unit_id} if cont else {}))
                    except Exception as exc:
                        logger.debug("会话池记录失败（不阻断）：%s", exc)
                if locked:
                    lock.release()
        if res.status == "needs_confirm":
            emit(UnitNeedsConfirm(unit_id=frag["fragment_id"],
                                  domain_id=frag["domain"],
                                  reason="关键碎片待确认",
                                  view=self._confirm_view(
                                      frag,
                                      self.runner.confirm_trigger(frag["domain"])),
                                  impact=self._confirm_impact(frag)))
        if res.status == "needs_answer":
            # E2-5（A10）：提问挂起事件（内容级信息补充——壳问题卡）
            from wuxing.events import UnitNeedsAnswer
            _pq = dict(getattr(res, "pending_question", None) or {})
            emit(UnitNeedsAnswer(unit_id=frag["fragment_id"],
                                 domain_id=frag["domain"],
                                 question_id=str(_pq.get("question_id", "")),
                                 questions=list(_pq.get("questions") or []),
                                 reason="执行中提问——请答复后继续",
                                 kind=str(_pq.get("kind", ""))))
        emit(UnitDone(unit_id=frag["fragment_id"], domain_id=frag["domain"],
                      status=res.status,
                      failure_class=getattr(res, "failure_class", "") or ""))
        for a in res.artifacts:
            emit(ArtifactWritten(unit_id=frag["fragment_id"], path=a.path, kind=a.kind))
        # 真测修复（REAL-4）：单元可能重写了产物——失效其缓存条目，后续单元的
        # 依赖注入必须读最新内容（FileCache 自身脏读/快照语义不变）
        self._invalidate_written(res)
        return res

    def _invalidate_written(self, res) -> None:
        """单元写出的路径 → 失效 file_cache 条目（REAL-4 跨单元陈旧读根因）。"""
        if self.file_cache is None or res is None:
            return
        invalidate = getattr(self.file_cache, "invalidate", None)
        if invalidate is None:
            return  # 测试樁/自定义缓存可不实现
        paths = list(getattr(res, "deliverables", None) or [])
        paths += [getattr(a, "path", "")
                  for a in (getattr(res, "artifacts", None) or [])]
        for p in paths:
            if p:
                try:
                    invalidate(str(p))
                except Exception as exc:
                    logger.debug("缓存失效失败（不阻断）：%s", exc)
