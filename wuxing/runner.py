"""执行单元：受控 agent loop（Q10：护栏内自主、护栏外引擎）。

护栏三件套：
  1. 轮数上限(max_loop_rounds)
  2. 调用预算(max_unit_budget)
  3. 工具白名单(域契约)——LLM 输出中 "TOOLCALL:<name> k=v" 行解析后校验，
     白名单外工具被拦截并记录（不阻断收敛：拦截后 LLM 可继续下一轮）。

契约校验：产物 schema 校验（P1 简化：产物存在性 + kind 匹配即视为通过；
          完整 JSON Schema 校验在 P4 随真 LLM 接入）。
"""
import logging
import pathlib

from wuxing.contracts import contract_check
from wuxing.domain_prompts import load_effective
from wuxing.protocols import UnitResult

# 骨架分期 P7（F-3f）：mixin 组合 + 支撑件兼容转出
from wuxing.runner_context import RunnerContextMixin
from wuxing.runner_llm import RunnerLlmMixin
from wuxing.runner_records import RunnerRecordsMixin
from wuxing.runner_support import (  # noqa: F401 (兼容转出：既有导入点)
    _KV_RE,
    _NO_SIDE_EFFECT,
    _REASONING_DELTA_CAP,
    _TEST_RUN_VERBS,
    _TOOLCALL_RE,
    MAX_PARALLEL_TOOLS,
    _is_side_effect_free,
    _is_test_path,
    _prepare_tool_result,
    _pytest_passed,
    _ReasoningDeltaThrottle,
    _requires_test_run,
    _test_run_passed,
    _wrap_tool_result,
)
from wuxing.runner_tools import RunnerToolsMixin
from wuxing.sandbox import policy_line
from wuxing.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


class Runner(RunnerContextMixin, RunnerLlmMixin, RunnerRecordsMixin, RunnerToolsMixin):
    def __init__(self, cfg, registry, workspace, llm, tools: list, llm_for=None,
                 confirm_gate=None, auto_confirm=True, reply_cache=None,
                 brain_memory=None, provenance=None, skills=None,
                 shared=None, trace=None, conversation=None,
                 ext_segments=None, skills_disabled=None,
                 hook_collect=None, state_root=None):
        self.cfg = cfg
        self.registry = registry
        self.ws = workspace
        # E3-1/R5（T2）：状态根（会话存档等账本→state_root；缺省=ws.root，零变化）
        self.state_root = (pathlib.Path(state_root) if state_root
                           else self.ws.root)
        self.llm = llm
        self.llm_for = llm_for  # (domain_id) -> LlmProvider；None = 单一 llm
        self.confirm_gate = confirm_gate
        self.auto_confirm = auto_confirm
        self.reply_cache = reply_cache  # P9 R1：精确键值缓存
        self.brain_memory = brain_memory  # P14：智脑案例归因
        self.provenance = provenance  # 3c：溯源链（Engine 装配）
        self.skills = skills  # SK：SkillRegistry（渐进披露——域详情/技能索引）
        self.shared = shared  # L3：任务级共享区（已完成碎片经验——有向增量注入）
        self.trace = trace  # L1-1：trace 采集器（评测原料——观测层）
        self.conversation = conversation
        # E2-1：扩展提示词段（Engine 解析 preset 过滤后透传）
        # E2-1：扩展提示词段（Engine 解析 preset 过滤后透传）
        self.ext_segments = list(ext_segments or [])
        # E2-4：预设技能禁用集（"*"=全禁）
        self.skills_disabled = {str(x) for x in (skills_disabled or ())}
        self.emit_event = None  # P4 T1：状态机事件发射器（orchestrator 注入）
        # E3-2（P1/H5）：钩子收集器（orchestrator 注入——UserPromptSubmit 注入用）
        self.hook_collect = hook_collect
        # P4 T1：状态机（idle→thinking→tool_executing→waiting→done/failed）
        self.state = "idle"
        # tools 可为 ToolRegistry（P5 守卫统一挂载）或 list（向后兼容）
        if isinstance(tools, ToolRegistry):
            self.tools = tools
        else:
            self.tools = ToolRegistry(tools)
        self._rounds = 0
        self._calls = 0
        self._blocked_tools = []
        self._fake_gate = None
        self._unit_budget = 0  # 域级预算（run_unit 设置——verify 减配）

    def _sanitize_enabled(self) -> bool:
        """SEC1：不可信内容净化开关（默认开；关闭=仅信封）。"""
        return bool(getattr(self.cfg, "content_trust_sanitize", True))

    def _trace_fields(self) -> dict:
        """Task7：真实测试埋点——会话轮次（无会话时为空——向后兼容）。"""
        if self.conversation is None:
            return {}
        try:
            return {"conversation_round": self.conversation.round_no,
                    "permission_profile": str(getattr(
                        self.cfg, "permission_profile", ""))}
        except Exception:
            return {}

    def _transition(self, state: str, unit_id: str = "", domain_id: str = ""):
        """P4 T1：状态转换（可观测——emit UnitStateChanged）。"""
        if state == self.state:
            return
        prev = self.state
        self.state = state
        if self.emit_event is not None:
            try:
                from wuxing.events import UnitStateChanged
                self.emit_event(UnitStateChanged(unit_id=unit_id,
                                                 domain_id=domain_id, state=state))
            except Exception as exc:
                logger.debug("单元状态事件发送失败（观测不阻断）：%s", exc)
        return prev

    def _emit_safety_blocked(self, unit_id: str, name: str, kwargs: dict,
                             error: str) -> None:
        """阶段 4（对齐项⑪）：安全拦截事件（流内警示卡数据源）。"""
        if self.emit_event is None:
            return
        try:
            from wuxing.events import SafetyBlocked
            cmd = kwargs.get("command", "")
            if not cmd:
                try:
                    import json as _json
                    cmd = _json.dumps(kwargs, ensure_ascii=False)
                except Exception:
                    cmd = ""
            self.emit_event(SafetyBlocked(
                unit_id=unit_id,
                domain_id=getattr(self, "_current_domain_id", ""),
                tool=name, command=str(cmd)[:300], reason=str(error)[:200]))
        except Exception as exc:
            logger.debug("安全拦截事件发送失败（观测不阻断）：%s", exc)

    def _maybe_cleanup(self) -> None:
        """E3-5（CU10）：单元收口后运行时清理（debounce——观测不阻断）。"""
        try:
            from wuxing.cleanup import maybe_cleanup
            maybe_cleanup(self.state_root, self.cfg, self.trace,
                          fields=self._trace_fields())
        except Exception as exc:
            # 清理是护城河不是生命线——失败静默（行为不阻断）
            logger.debug("运行时清理失败（不阻断）：%s", exc)

    @staticmethod
    def _args_key(kwargs: dict) -> str:
        """工具参数指纹（完整 sha256——重复计数键；结构化参数安全）。

        六轮审查 A1：list/dict 参数不可哈希——不得直接作字典键；
        不可 JSON 序列化的值降级 repr（键序稳定）。
        """
        import hashlib
        import json as _json
        try:
            payload = _json.dumps(kwargs, sort_keys=True, ensure_ascii=False,
                                  default=str)
        except (TypeError, ValueError):
            payload = repr(sorted((str(k), repr(v)) for k, v in kwargs.items()))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _arg_hash(kwargs: dict) -> str:
        """L1-1：工具参数指纹（8 位 sha256——trace 可判重复调用/参数漂移）。"""
        return Runner._args_key(kwargs)[:8]

    def _select_tools(self, whitelist: list, goal_text: str) -> list:
        """L2-3（FC 层2 检索）：工具超阈值 → 按碎片文本 jieba 词元 Jaccard 选 top-k。

        - 确定性：同片段同选择（单元内前缀稳定——缓存安全）
        - 强制保留（alwaysLoad）：delegate/load_skill（引擎级——委托/渐进披露
          不可剪）+ 契约物证工具（write_artifact/write_file/read_file/
          read_dependency——require_write/require_read 域契约硬需求；剪掉
          必导致单元失败，见 2026-10-03 Wave-1 回归）
        - 兜底：低于阈值/空文本/无查询词元/无得分 → 全量（现状行为）
        """
        threshold = getattr(self.cfg, "tool_retrieval_threshold", 10)
        if threshold <= 0 or len(whitelist) <= threshold or not goal_text:
            return whitelist
        from wuxing.cache import _tokens_for_sim
        q = _tokens_for_sim(goal_text)
        if not q:
            return whitelist
        keep = {"delegate", "load_skill",
                "write_artifact", "write_file",
                "read_file", "read_dependency"}
        scored, forced = [], []
        for t in whitelist:
            if t.name() in keep:
                forced.append(t)
                continue
            vt = _tokens_for_sim(t.name() + " " + (t.description() or ""))
            sim = len(q & vt) / len(q | vt) if (q | vt) else 0.0
            scored.append((sim, t))
        scored.sort(key=lambda x: (-x[0], x[1].name()))
        top = [t for _s, t in scored[:max(0, getattr(self.cfg,
                                                     "tool_retrieval_top_k", 8)
                                           - len(forced))]]
        kept = forced + top
        if not kept:
            return whitelist
        # Task C2（Wave-1）：检索决策落 trace（归因可观测——不改选择结果）
        if self.trace is not None:
            kept_names = {t.name() for t in kept}
            self.trace.log("tool_retrieval", unit_id="", domain="",
                           query=goal_text, threshold=threshold,
                           top_k=int(getattr(self.cfg,
                                             "tool_retrieval_top_k", 8)),
                           kept=[t.name() for t in kept],
                           dropped=[t.name() for t in whitelist
                                    if t.name() not in kept_names])
        return kept

    def _needs_confirm(self, domain_id: str, unit_id: str) -> bool:
        """判定源：confirm_gate 优先；无 gate 时按 cfg.confirm_threshold 简化（>=1 全确认）。"""
        if self.confirm_gate is not None:
            return self.confirm_gate.needs_confirm(domain_id, unit_id)
        return self.cfg.confirm_threshold >= 1.0

    def confirm_trigger(self, domain_id: str) -> str:
        """确认触发源（视图/审计用）——与 `_needs_confirm` 同源语义，不重复判定。"""
        gate = self.confirm_gate
        if gate is not None and domain_id in getattr(
                gate, "always_confirm_domains", ()):
            return "domain_policy"
        return "threshold"

    def _llm(self, domain_id: str, fragment_key: str | None = None,
             candidate: int = 0):
        if self.llm_for is not None:
            try:
                return self.llm_for(domain_id, fragment_key, candidate)
            except TypeError:
                return self.llm_for(domain_id, fragment_key)  # 兼容旧回调签名
        return self.llm

    def run_unit(self, unit_id: str, domain_id: str, params: dict,
                 resume_session: list | None = None,
                 bypass_confirm: bool = False,
                 continue_from: list | None = None,
                 cancel=None, llm_candidate: int = 0) -> UnitResult:
        """P4 T3：resume_session（消息级断点）——从存档历史续跑而非重新开始。

        断点语义：历史已含 system/prompt/工具结果 → 模型直接续答；
        跳过首轮缓存查询（续跑不是新任务——缓存键语义不适用）。
        bypass_confirm：单次放行（A2 修复——人工确认后的续跑：用户已批准该
        单元，不得再次挂起——否则 verify 域 always_confirm 死循环）。
        continue_from（FSC，2026-09-11 设计）：跨轮会话延续——保留历史作
        前缀（append-only），新 prompt 追加在尾部（缓存前缀不破）。
        """
        if cancel is not None and cancel.is_set():
            return self._cancelled_unit(unit_id, domain_id)
        self._max_tool_chars = getattr(self.cfg, "context_max_chars", 8192)
        self._cur_params = params  # 智脑分级：粒度数据透传
        domain = self.registry.get(domain_id)
        # Q1：模式解析 + 域工具白名单（抽为子步骤——行为不变）
        whitelist, _minimal, _pure, _conv_name = self._resolve_unit_mode(
            domain, domain_id)

        # B2（审查）：域级预算提前计算——system 声明必须与实际一致
        # （此前声明 cfg 默认而 verify 实际减配 3——模型被误导规划）
        self._unit_budget = (min(getattr(self.cfg, "max_unit_budget", 5), 3)
                             if domain_id == "verify"
                             else getattr(self.cfg, "max_unit_budget", 5))
        # R2 拆分 Phase 1：消息组装 → prompt_builder（缓存红线唯一维护点）
        from wuxing.prompt_builder import (
            build_prompt,
            build_skill_index_msg,
            project_task_safe,
            system_sections,
            tool_schemas,
        )
        llm = self._llm(domain_id, params.get("fragment_key"), llm_candidate)
        _native = getattr(llm, "supports_native_tools", lambda: True)()
        prompt = build_prompt(domain, params,
                              project_task_safe(params.get("task", ""),
                                                self.cfg),
                              params.get("deliverables") or [],
                              # 心跳（批 1）：极简两分支模式级让位（显式配置不生效——
                              # 需要心跳请用非极简模式；设计 §4.1）
                              heartbeat=(bool(getattr(
                                  self.cfg, "progress_heartbeat_enabled", True))
                                  and not _minimal),
                              references_text=params.get("references", ""))
        # L4 真跑发现：交付物语义注入——模型未知本碎片交付类型→无限探索
        # 重大优化清单 #3：用户自定义域提示词（pure 跳过——fail-visible）
        _custom = None
        try:
            _dp = load_effective(self.ws.root, domain_id)
        except Exception as exc:  # 读取失败不影响主流程（诊断可见）
            logger.debug("域提示词读取失败：%s", exc)
            _dp = {"notes": "", "addendum": "", "problems": [str(exc)]}
        for _p in _dp.get("problems") or []:
            if self.trace is not None:
                try:
                    self.trace.log("domain_prompts_problem", unit_id, domain_id,
                                   problem=str(_p)[:300])
                except Exception as exc:
                    logger.debug("域提示词诊断事件记录失败：%s", exc)
        if _dp.get("notes") or _dp.get("addendum"):
            if _pure:
                if self.trace is not None:
                    try:
                        self.trace.log("domain_prompts_skipped", unit_id,
                                       domain_id, reason="pure")
                    except Exception as exc:
                        logger.debug("域提示词跳过事件记录失败：%s", exc)
            else:
                _custom = {"notes": _dp.get("notes") or "",
                           "addendum": _dp.get("addendum") or ""}
        _sections = system_sections(domain, whitelist, _native,
                                    self._unit_budget, thin=_minimal,
                                    custom=_custom)
        system_text = "".join(s["text"] for s in _sections)
        # R3-2/T4：模型可见沙箱策略行（字节稳定——同状态逐字节一致）
        system_text += "\n" + policy_line(
            bool(getattr(self.cfg, "sandbox_enabled", True)), self.ws.root,
            mode=str(getattr(self.cfg, "sandbox_mode", "native") or "native"),
            template=str(getattr(self.cfg, "sandbox_container_template", "") or ""))
        self._tool_schemas = tool_schemas(whitelist)
        # 批 1：pure 不构建技能索引（不注入——设计 §4.2）
        skill_index_msg = (None if (_pure or "*" in self.skills_disabled)
                           else build_skill_index_msg(
                               self.skills,
                               disabled=self.skills_disabled))
        # E2-1：扩展提示词段（按单元域过滤；pure 不注入——同技能索引纪律）
        ext_seg_msg = None
        _seg_parts: list = []
        if not _pure and self.ext_segments:
            _seg_parts = [str(s.get("text") or "")
                          for s in self.ext_segments
                          if not s.get("domains")
                          or domain_id in s.get("domains")]
            if _seg_parts:
                _seg_text = "\n\n".join(_seg_parts)
                ext_seg_msg = {"role": "user",
                               "content": "[扩展提示]\n" + _seg_text}
                if self.trace is not None:
                    try:
                        self.trace.log("extension_prompt", unit_id,
                                       domain_id,
                                       count=len(_seg_parts),
                                       chars=len(_seg_text))
                    except Exception as exc:
                        logger.debug("扩展提示词事件记录失败（观测不阻断）：%s", exc)
        # Q1：消息装配（抽为子步骤——行为不变）
        self._messages, _sizes, _src = self._build_unit_messages(
            unit_id, prompt, system_text,
            conv_name=_conv_name, resume_session=resume_session,
            continue_from=continue_from, skill_index_msg=skill_index_msg,
            ext_seg_msg=ext_seg_msg, pure=_pure, domain_id=domain_id)

        # E3-2（P1/H5）：UserPromptSubmit 注入点——发射事件 + 收集 additional_context
        # （尾插用户消息——系统段/历史段前缀不变，缓存友好）
        self._emit_user_prompt_submit(unit_id, domain_id, prompt)

        # E2-3（⑰ · PP1/CC6）：节级哈希 → trace（只读诊断——缓存 miss 归因：
        # 哪一节变了；不参与装配决策，失败不阻断）
        if self.trace is not None:
            try:
                from wuxing.prompt_sections import (
                    hash_sections,
                    hash_text,
                    message_hashes,
                )
                _hashes = {f"sys:{k}": v for k, v in
                           hash_sections(_sections).items()}
                _sys_all = "".join(s["text"] for s in _sections)
                _hashes["sys:policy"] = hash_text(system_text[len(_sys_all):])
                _hashes.update({f"msg:{k}": v for k, v in
                                message_hashes(self._messages).items()})
                self.trace.log("prompt_sections", unit_id, domain_id,
                               hashes=_hashes, **self._trace_fields())
            except Exception as exc:
                logger.debug("节级哈希记录失败（观测不阻断）：%s", exc)

        # Q1：窗口预算强制（抽为子步骤——行为不变）
        self._apply_context_budget(llm, _src, unit_id, domain_id, _sizes)

        # P4 T1：状态机——单元开始（idle→thinking）
        self._current_domain_id = domain_id
        # L1-1：trace 单元开始（评测原料起点）
        if self.trace is not None:
            self.trace.log("unit_started", unit_id, domain_id,
                           **self._trace_fields(), **_sizes)
        self._transition("thinking", unit_id, domain_id)        # P5：确认关口——关键碎片挂起（auto_confirm=True 仅发事件不阻塞；
        # 事件发射由 orchestrator 负责——审查修正：删除死分支）
        # 批 1：pure 且配置开启 → 本单元强制自动（事件照发、不阻塞——设计 §4.1）
        _auto_confirm = self.auto_confirm or (
            _pure and bool(getattr(self.cfg, "minimal_pure_auto_confirm", True)))
        if self._needs_confirm(domain_id, unit_id) and not _auto_confirm \
                and not bypass_confirm:
            self._transition("waiting", unit_id, domain_id)
            if self.trace is not None:
                # E2-4（B6）：审计对（asked）——无应答 → 默认不执行（fail-closed）
                self.trace.log("confirm_asked", unit_id, domain_id,
                               reason="confirm: waiting for user",
                               surface="unit_confirm",
                               **self._trace_fields())
            return UnitResult(unit_id=unit_id, domain_id=domain_id,
                              status="needs_confirm",
                                  error="confirm: waiting for user")

        # Q1：单元运行态初始化（抽为子步骤——行为不变）
        artifacts, logs = self._init_unit_runtime(
            unit_id, domain_id, params, llm, resume_session, continue_from)
        # Task 4-1（流式专项）：最后一次助手文本（收口时落 UnitResult.reply）
        last_reply = ""
        while self._rounds < self._hard_rounds \
                and self._calls < self._hard_budget:
            # 壳 P1 对齐项②：轮次边界取消检查（协作式；不 kill 线程）
            if cancel is not None and cancel.is_set():
                return self._cancelled_unit(unit_id, domain_id)
            self._rounds += 1
            self._calls += 1
            # P0 修正（S2 修复）：ReplyCache 仅单元【首轮】查询（跨单元/会话复用保留）；
            # 单元内轮次不再查缓存——同键毒化（重复副作用/LLM 不参与）此前导致循环锁死。
            # P4 T3：断点续跑场景跳过首轮缓存查询（续跑 ≠ 新任务）
            cache_key = None
            if self.reply_cache is not None and self._rounds == 1 and not resume_session:
                cache_key = f"{domain_id}|{prompt}"
                cached = self.reply_cache.get(cache_key)
                if cached is None:
                    # P1 T3（债 4）：R3 语义检索——精确 miss 后高相似复用（微漂移）
                    val, sim = self.reply_cache.similar_get(cache_key)
                    if val is not None:
                        cached = val
                        self._semantic_hit_used = True
                        self._cache_breakdown["semantic_hits"] += 1
                        logs.append(f"[cache] similar hit (sim={sim:.2f})")
                if cached is not None:
                    out = cached
                else:
                    self._cache_breakdown["first_round_misses"] += 1

                    def _compute_and_store(cache_key=cache_key):
                        value = self._chat_traced(llm, unit_id, domain_id)
                        self.reply_cache.put(cache_key, value)
                        return value

                    try:
                        # I1（v65）：同键并发单飞——leader 计算并写缓存，waiter 复用结果
                        out = self.reply_cache.singleflight(
                            cache_key, _compute_and_store)
                    except Exception as e:
                        self._transition("failed", unit_id, domain_id)
                        return self._provider_failure(unit_id, domain_id, artifacts,
                                                      logs, llm, params, e)
            else:
                try:
                    out = self._chat_traced(llm, unit_id, domain_id)
                except Exception as e:
                    self._transition("failed", unit_id, domain_id)
                    return self._provider_failure(unit_id, domain_id, artifacts,
                                                  logs, llm, params, e)
            # 壳 P1 对齐项⑤：进度心跳——解析模型自报进度 → progress 事件
            self._emit_progress_reports(unit_id, domain_id, out)
            # Task 4-1：最后一次助手文本——工具轮携带文本也算（真实模型常同轮
            # 「写产物 + 总体回复」）；纯工具轮无文本 → 空（不冒充总体回复）
            _text_now = out.text if hasattr(out, "tool_calls") else out
            last_reply = str(_text_now or "").strip()
            # 每轮 LLM 作答后回到 thinking（工具执行/回填将在其内完成）
            self._transition("thinking", unit_id, domain_id)
            # P5：支持原生 ToolCallResult；兼容纯字符串（旧路径：文本协议解析）
            if hasattr(out, "tool_calls"):
                # 壳 P1 对齐项②：工具批前取消检查（避免取消后仍执行副作用工具）
                if cancel is not None and cancel.is_set():
                    return self._cancelled_unit(unit_id, domain_id)
                prev_logs = len(logs)
                # M1-4：工具级并行（无副作用组并发——CPU 速度主轴；回填保持调用序）
                self._execute_tool_calls_batch(out.tool_calls, whitelist, logs,
                                               unit_id=unit_id)
                tool_msgs = logs[prev_logs:]  # 本轮工具结果（[tool]/[tool:error]/[guard]/[warn]）
                logs.append(out.text)
                contract_out = out.text
                self._append_round_history(out.text, tool_msgs, unit_id=unit_id)
            else:
                prev_logs = len(logs)
                self._exec_toolcalls(out, whitelist, logs, unit_id=unit_id)
                tool_msgs = logs[prev_logs:]
                logs.append(out)
                contract_out = out
                self._append_round_history(out, tool_msgs, unit_id=unit_id)
            # L4 真跑发现：声明轮时序缺口——最后一轮前注入轮次压力提示（动态尾部）
            remaining = self._unit_budget - self._calls
            _baseline_hit_now = (self._rounds >= int(self.cfg.max_loop_rounds)
                                 or self._calls >= self._unit_budget)
            if remaining <= 1 and not _baseline_hit_now:
                self._messages.append({
                    "role": "user",
                    "content": f"（第 {self._rounds}/{self._unit_budget} 轮，剩余 {remaining} 轮——"
                                f"若产物已产出，请直接输出完成声明；若未产出，请立即调用写工具并输出完成声明）"})
            # P4 T2：会话持久化——本轮【增量】（LLM 文本 + 工具结果）
            if self._session is not None:
                delta = []
                _round_text = out.text if hasattr(out, "text") else out
                # 跨 provider 兼容（E3-4 真跑 2026-10-04）：纯工具轮无文本 →
                # 不落空 content 消息（Moonshot 空消息 400 实测）
                if str(_round_text or "").strip():
                    delta.append({"role": "user", "content": _round_text})
                for m in tool_msgs:
                    if self._sanitize_enabled():
                        from wuxing.content_trust import sanitize_untrusted
                        m = sanitize_untrusted(m).clean
                    delta.append({"role": "user", "content": m})
                self._session.append(round_no=self._rounds,
                                     state="thinking", messages=delta)
            # E2-5（A10）：提问挂起——本轮（含 [ask] 标记）已入存档，停轮等答复
            # （fail-closed：无答复不继续；答复由 engine.answer_unit 以 resume 注入）
            if getattr(self, "_ask_pending", None) is not None:
                return self._pause_for_answer(unit_id, domain_id, artifacts,
                                              logs, last_reply)
            claim_report: list = []
            verdict = contract_check(domain, contract_out, unit_id, artifacts,
                                     logs, self._write_ok, self._read_ok,
                                     ws=self.ws,
                                     deliverables=self._deliverables,
                                     require_run=self._require_run,
                                     run_ok=self._run_ok,
                                     claim_report=claim_report)
            # L1-1：契约判定 trace（每轮——评测归因：收敛轮次/失败轮次)
            if self.trace is not None:
                self.trace.log("contract_check", unit_id, domain_id,
                               round=self._rounds, passed=verdict is not None,
                               **self._trace_fields())
            # O3/C1（软观测）：声称-交付物一致性——通过后留痕 + 一次性提醒
            # （不驳回；数据积累后定硬档——O3-D1）
            if verdict is not None and claim_report:
                if self.trace is not None:
                    self.trace.log("claim_mismatch", unit_id, domain_id,
                                   round=self._rounds,
                                   missing=list(claim_report),
                                   **self._trace_fields())
                if not self._claim_nudge:
                    self._claim_nudge = True
                    self._messages.append({
                        "role": "user",
                        "content": ("[契约] 以下声称产物未检出："
                                    + "、".join(f"`{p}`" for p in claim_report)
                                    + "——请补写文件或更正声称。")})
            # 真测缺陷（RT5）：要求运行测试但无成功物证 → 明确提醒（
            # 模型可见；一次）——防「未跑测试也声明完成」的假收敛
            if (verdict is None and self._require_run and not self._run_ok
                    and not self._run_nudge):
                self._run_nudge = True
                self._messages.append({
                    "role": "user",
                    "content": ("[契约] 本单元要求运行测试并以通过结果为准——"
                                "机制未检测到成功的测试运行记录。请运行测试"
                                "（如 `python -m pytest -q` 或 `python -m unittest`）"
                                "并确认通过输出；若无法运行请说明原因。")})
                if self.trace is not None:
                    self.trace.log("contract_run_nudge", unit_id, domain_id,
                                   round=self._rounds,
                                   **self._trace_fields())
            # M1-1（数据驱动）：verify 依赖产物缺失 → 机制兜底「不通过」——
            # 验收对象不存在=确定不通过（无需模型自觉——read 循环修复）
            if verdict is None and domain_id == "verify" \
                    and self._verify_deps_missing():
                out = "结论：不通过（机制裁决——验收产物缺失）"
                verdict = contract_check(domain, out, unit_id, artifacts,
                                         logs, self._write_ok, self._read_ok,
                                         ws=self.ws,
                                         deliverables=self._deliverables,
                                         require_run=self._require_run,
                                         run_ok=self._run_ok)
                if verdict is not None and self.trace is not None:
                    self.trace.log("auto_verdict", unit_id, domain_id,
                                   round=self._rounds, reason="missing_evidence",
                                   **self._trace_fields())
            # 真测裁决 W2：基线到达 → 机械评分 + 收敛自评（不失败）；停滞才早停
            if (self._rounds >= int(self.cfg.max_loop_rounds)
                    or self._calls >= self._unit_budget):
                progress = (len(self._deliverables),
                            sum(1 for x in logs if str(x).startswith("[tool")))
                if progress == self._progress_mark and verdict is None:
                    self._stall += 1
                else:
                    self._stall = 0
                self._progress_mark = progress
                if not self._converge_injected:
                    self._converge_injected = True
                    self._messages.append({
                        "role": "user",
                        "content": (
                            f"[收敛检查] 已达基线（轮 {self._rounds}/"
                            f"{int(self.cfg.max_loop_rounds)}，调用 {self._calls}/"
                            f"{self._unit_budget}）——机械评分：写物证 "
                            f"{len(self._deliverables)} 件、读证据 "
                            f"{'已' if self._read_ok else '未'}执行、"
                            f"本轮{'有' if self._stall == 0 else '无'}进展。"
                            f"请自评：①若已完成→立即输出完成声明"
                            f"（verify 输出结论）；②若未完成→给出最小剩余步骤"
                            f"并继续执行（安全上限：{self._hard_rounds} 轮/"
                            f"{self._hard_budget} 调用）")})
                    if self.trace is not None:
                        self.trace.log("converge_gate", unit_id, domain_id,
                                       round=self._rounds,
                                       **self._trace_fields())
                if self._stall >= 3 and verdict is None:
                    # W4.4（真测裁决）：停滞窗口 2→3（为真实模型的分析轮留白）
                    self._fail_reason = "guard: stalled (no progress)"
                    break
            if verdict is not None:
                self._brain_record(unit_id, domain_id, llm, success=True,
                                   fragment_key=params.get("fragment_key"))
                self._provenance_record(unit_id, params, domain_id, llm, verdict.status,
                                        verdict.artifacts)
                verdict.metrics = self._unit_metrics(llm)
                verdict.metrics["memory"] = dict(self._mem_meta)
                verdict.deliverables = list(self._deliverables)
                verdict.reply = last_reply  # Task 4-1：模型总体回复（会话行/卡片数据面）
                if self._semantic_hit_used:
                    self._cache_breakdown["semantic_ok"] += 1
                verdict.metrics["cache_breakdown"] = dict(self._cache_breakdown)
                self._transition("done", unit_id, domain_id)
                if self.trace is not None:
                    self.trace.log("unit_done", unit_id, domain_id,
                                   status="ok",
                                   verdict_fail=bool(getattr(verdict, "verdict_fail", False)),
                                   **self._trace_fields())
                if self._session is not None:
                    self._session.append(round_no=self._rounds, state="done",
                                         messages=[], status="ok")
                self._shared_record(unit_id, params, verdict)
                self._maybe_cleanup()  # E3-5（CU10）：收口清理（debounce）
                return verdict
        # 预算/轮数耗尽 → failed（P1 直接标记；P6 接 Repairer 降级链）
        self._transition("failed", unit_id, domain_id)
        if self.trace is not None:
            self.trace.log("unit_done", unit_id, domain_id, status="failed",
                           verdict_fail=False, **self._trace_fields())
        if self._session is not None:
            self._session.append(round_no=self._rounds, state="failed",
                                 messages=[], status="failed")
        _cls, _msg = self._exit_failure()
        res = UnitResult(unit_id=unit_id, domain_id=domain_id, status="failed",
                         artifacts=artifacts, logs=logs, reply=last_reply,
                         error=_msg, failure_class=_cls)
        self._shared_record(unit_id, params, res)
        res.metrics = self._unit_metrics(llm)
        res.metrics["memory"] = dict(getattr(self, "_mem_meta", {}))
        res.deliverables = list(self._deliverables)
        res.metrics["cache_breakdown"] = dict(self._cache_breakdown)
        self._brain_record(unit_id, domain_id, llm, success=False, error=res.error,
                           logs=logs, fragment_key=params.get("fragment_key"))
        self._provenance_record(unit_id, params, domain_id, llm, "failed", artifacts)
        self._maybe_cleanup()  # E3-5（CU10）：收口清理（debounce）
        return res
