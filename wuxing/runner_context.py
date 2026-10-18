"""Runner 装配/上下文子系统（骨架分期 P7/F-3f：自 runner.py 提取的方法组）。

来源：`wuxing/runner.py`（2026-10-06 迁移；方法体逐字节保持）。
理由：F-3 巨型文件分期——装配/上下文面落隔离模块（mixin 组合）；**不得 import engine**（守卫）。
"""

from wuxing.runner_support import _requires_test_run


class RunnerContextMixin:
    # ---- Q1 拆分：run_unit 子步骤（行为保持——逐字迁移） ----

    def _resolve_unit_mode(self, domain, domain_id) -> tuple:
        """模式解析 + 域工具白名单（pure 核心集过滤 + 检索选择）。

        返回 (whitelist, minimal, pure, conv_name)。
        """
        from wuxing.session_modes import resolve as _resolve_mode
        _conv_name = ""
        try:
            if self.conversation is not None:
                _conv_name = self.conversation.path.name
        except AttributeError:
            _conv_name = ""
        _mode = _resolve_mode(
            self.ws.root, conversation=_conv_name,
            default=getattr(self.cfg, "mode_default", "minimal-standard"))
        _minimal = _mode["mode"] == "minimal"
        _pure = _minimal and _mode["variant"] == "pure"
        whitelist = self.tools.filter(domain.tool_whitelist, domain_id=domain_id)
        if _pure:
            _core = set(getattr(self.cfg, "minimal_pure_tools", ()) or ())
            whitelist = [t for t in whitelist if t.name() in _core]
        # L2-3（FC 层2）→ C-3：工具检索输入改为**域级键**（同域碎片 tools 参数
        # 一致——跨碎片前缀稳定；碎片文本不参与——MCP 大集场景前缀优先）。
        # engine_level 工具强制保留；确定性选择（同输入同结果）
        whitelist = self._select_tools(
            whitelist, f"域 {domain_id} {domain.title}")
        return whitelist, _minimal, _pure, _conv_name

    def _apply_context_budget(self, llm, src, unit_id, domain_id,
                              sizes) -> None:
        """A3（2026-09-22）/G7（2026-09-26）：窗口预算强制（会话预算优先；
        自动链滞回；0=关闭；优先级裁剪；仅投影层——池/存档零改写）。
        """
        from wuxing.context_budget import apply_auto_trim, effective_budget
        from wuxing.context_preview import estimate_tokens
        _window = 0
        try:
            _spec = llm.spec() if hasattr(llm, "spec") else ""
        except Exception:
            _spec = ""
        from wuxing.context_window import resolve_context_window
        _window = resolve_context_window(
            _spec, getattr(self.cfg, "model_context_windows", None),
            getattr(self.cfg, "default_context_window", 200_000))
        _est_total = sum(estimate_tokens(str(m.get("content", "")))
                         for m in self._messages)
        _trigger = effective_budget(
            self.cfg, _window,
            session_budget=int(src.get("budget_tokens") or 0))
        if (_trigger > 0 and _est_total > _trigger
                and bool(getattr(self.cfg, "auto_compact_llm_enabled", False))):
            # G7：LLM 摘要链——压缩行自下一轮装配生效；本轮由机械链兜底
            self._compact_llm_history(unit_id, _trigger, _window)
        self._messages, _trimmed, _budget_used, _auto = apply_auto_trim(
            self._messages, self.cfg, _window, estimate_tokens,
            session_budget=int(src.get("budget_tokens") or 0))
        if _trimmed:
            sizes["history_chars"] = sum(
                len(str(m.get("content", ""))) for m in self._messages
                if str(m.get("content", "")).startswith("[会话历史]"))
            if self.trace is not None:
                self.trace.log("context_trimmed", unit_id, domain_id,
                               trimmed=_trimmed, budget_tokens=_budget_used,
                               auto=_auto, **self._trace_fields())

    def _build_unit_messages(self, unit_id, prompt, system_text, *,
                             conv_name, resume_session, continue_from,
                             skill_index_msg, ext_seg_msg, pure,
                             domain_id: str = "") -> tuple:
        """A1/B 期：消息装配（resume/continue/首轮分支 + 摘要/历史/技能/扩展/共享）
        + 注入段长记录。返回 (messages, sizes, src)。

        S5-A/S5-B（A13 裁决 2026-10-06）：首轮分支历史前置于摘要（append-only
        前缀位——跨轮增量可命中）；折叠时发 trace `history_folded`。
        """
        # A1（2026-09-22）：会话级来源开关（默认全开——旧数据装配字节不变）
        from wuxing.context_sources import resolve as _resolve_sources
        # conv_name 已在模式解析段计算（复用——不重复取会话名）
        src = _resolve_sources(
            self.state_root, conversation=conv_name, unit=unit_id,
            default_budget=int(getattr(self.cfg, "context_budget_tokens", 0) or 0))
        # B 期（2026-09-22）：真实注入段长（实测参考——上下文投影数据源）
        # 精化（2026-09-23）：同步记录同源 token 估算——预览预算映射与真实装配同口径
        from wuxing.context_preview import estimate_tokens as _est_tokens
        sizes = {"system_chars": len(system_text),
                 "system_est_tokens": _est_tokens(system_text),
                 "skills_chars": 0, "extensions_chars": 0, "history_chars": 0,
                 "digest_chars": 0, "continue_chars": 0, "shared_chars": 0}
        from wuxing.prompt_builder import (
            build_conversation_msg,
            build_prev_digest_msg,
            build_shared_msg,
        )
        messages: list = []
        if resume_session:
            # P4 T3：断点续跑——历史完整（system/prompt/回填均在存档中）
            messages = [dict(m) for m in resume_session]
        elif continue_from:
            # FSC（2026-09-11）：保留历史（append-only 前缀）+ append 新 prompt
            # ——延续内容为缓存命中，新指令才是 miss
            sizes["continue_chars"] = sum(
                len(str(m.get("content", ""))) for m in continue_from)
            messages = [dict(m) for m in continue_from]
            messages.append({"role": "user", "content": prompt})
            if ext_seg_msg is not None:
                messages.append(ext_seg_msg)
                sizes["extensions_chars"] = len(
                    str(ext_seg_msg.get("content", "")))
        else:
            messages = [{"role": "system", "content": system_text}]
            # B 模式：会话历史段（system 后——S5-A 历史前置：append-only 前缀位，
            # 跨轮增量可命中；同轮跨碎片逐字节一致）
            _conv_msg = None
            _folded = 0
            _hist_max = getattr(self.cfg, "conversation_max_chars", 4000)
            if src["history"]:
                _conv_msg, _folded = build_conversation_msg(
                    self.conversation, max_chars=_hist_max, with_meta=True)
            if _conv_msg is not None:
                messages.append(_conv_msg)
                sizes["history_chars"] = len(
                    str(_conv_msg.get("content", "")))
                if _folded and self.trace is not None:
                    # S5-B（A13 裁决 2026-10-06）：折叠事件机械化（评测/归因）
                    self.trace.log("history_folded", unit_id, domain_id,
                                   folded=_folded,
                                   chars=sizes["history_chars"],
                                   max_chars=_hist_max,
                                   **self._trace_fields())
            # FSC 低匹配回退（用户裁决 2026-09-12）：上一轮全部碎片上下文压缩
            # ——S5-A 后置：摘要逐轮变化，不再打断历史段增量缓存
            if src["digest"] and getattr(self.cfg, "fsc_enabled", False) \
                    and getattr(self.cfg, "fsc_fallback_digest", True):
                _digest_msg = build_prev_digest_msg(
                    self.conversation,
                    getattr(self.cfg, "fsc_digest_max_chars", 2000))
                if _digest_msg is not None:
                    messages.append(_digest_msg)
                    sizes["digest_chars"] = len(
                        str(_digest_msg.get("content", "")))
            messages.append({"role": "user", "content": prompt})
            if not pure and src["skills"] and skill_index_msg is not None:
                messages.append(skill_index_msg)
                sizes["skills_chars"] = len(
                    str(skill_index_msg.get("content", "")))
            if ext_seg_msg is not None:
                messages.append(ext_seg_msg)
                sizes["extensions_chars"] = len(
                    str(ext_seg_msg.get("content", "")))
        # L3：任务级共享段注入（已完成碎片经验——尾部动态；有向增量）
        # 批 1：pure 不注入共享经验（设计 §4.2）
        _shared_msg = None if pure else build_shared_msg(self.shared, unit_id)
        if _shared_msg is not None:
            # H6（E3-5）：召回注入帧标注——call-time 提供（不写 transcript/session；
            # 发送前由 _provider_messages 剥除内部键；档案写入由 SessionLog 过滤）
            _shared_msg = {**_shared_msg, "_call_time": True}
            messages.append(_shared_msg)
            sizes["shared_chars"] = len(str(_shared_msg.get("content", "")))
        # O2-2 P2：旧快照替换（投影层 keep-latest；存档零改写——G3）
        from wuxing.snapshot_supersede import supersede_old_snapshots
        _superseded = supersede_old_snapshots(messages)
        if _superseded and self.trace is not None:
            self.trace.log("snapshot_superseded", unit_id, domain_id,
                           replaced=_superseded)
        return messages, sizes, src

    def _init_unit_runtime(self, unit_id, domain_id, params, llm,
                           resume_session, continue_from) -> tuple:
        """单元运行态初始化（轮次/预算硬上限、物证标志、会话日志、usage 快照）。

        返回 (artifacts, logs)——空列表（行为同原内联块）。
        """
        self._rounds = 0
        self._calls = 0
        # 真测裁决 W2（2026-09-26）：轮数/预算只是基线（到达 → 机械评分 + 自评）；
        # 安全上限是唯一硬停
        _hard_r = int(getattr(self.cfg, "max_loop_rounds_hard", 0) or 0)
        _hard_b = int(getattr(self.cfg, "max_unit_budget_hard", 0) or 0)
        self._hard_rounds = max(int(self.cfg.max_loop_rounds), _hard_r)
        self._hard_budget = max(int(self._unit_budget), _hard_b)
        self._converge_injected = False
        self._stall = 0
        self._progress_mark = (0, 0)
        self._fail_reason = ""
        self._blocked_tools = []
        # E2-5（L3）：清单随单元开始清空（run 作用域——防跨单元串表）
        _todo_tool = self.tools.get("todo_write") if self.tools else None
        if _todo_tool is not None and hasattr(_todo_tool, "reset"):
            _todo_tool.reset()
        # E2-5（A10）：提问运行态——挂起槽 + 跨 resume 计数（历史 [ask] 标记；
        # 每单元 ≤3 次由 runner 拦截）
        self._ask_pending = None
        self._ask_seq = sum(
            1 for m in (resume_session or [])
            if str(m.get("content", "")).lstrip().startswith("[ask]"))
        # B4（审查）：重复检测序列不得跨单元泄漏——共享 Runner（confirm 路径）
        # 连续单元各记各的（否则上一单元同参序列计入本单元——假阳性提醒）
        # #3（2026-09-11 报告 #6）：改为单元内同名同参计数（含非连续——45.4% 重复率主体）
        self._tool_key_counts = {}
        # B2：system 声明后行（_unit_budget 已提前计算——verify 减配语义一致）
        # P0 T3：物证累计（S5）——write_ok=写工具成功；read_ok=读工具已执行（检查行为）
        self._write_ok = False
        self._read_ok = False
        # 真测缺陷（RT5）：显式要求「运行 pytest」的 execute 单元需成功运行物证
        self._require_run = (domain_id == "execute"
                             and _requires_test_run(params.get("goal", "")))
        if self._require_run and self.trace is not None:
            self.trace.log("run_required", unit_id, domain_id, source="goal")
        self._run_ok = False
        self._run_attempted = False  # S1-B：运行尝试证据位（跑过未过的判定基座）
        self._run_nudge = False
        # O3/C1（软观测）：声称缺件提醒一次性标记（trace 每次、提醒一次）
        self._claim_nudge = False
        # S-C：真实交付物追踪（写工具成功写出 → deliverables——验收语义闭环）
        self._deliverables = []
        # 命中率细分（T2）：语义命中质量 + 失效结构（S2 毒化残留检测）
        self._semantic_hit_used = False
        self._cache_breakdown = {"semantic_hits": 0, "semantic_ok": 0,
                                 "first_round_misses": 0, "later_round_misses": 0}
        # P4 T2：会话日志（append-only——消息级回放素材；增量语义——审查修正）
        self._session = None
        try:
            from wuxing.session import SessionLog
            # 真实测试暴露（2026-09-07）：session 文件名含会话轮次——unit_id
            # 每轮重用（F-0001…）→ 旧命名跨轮覆盖丢诊断数据。
            _rn = (self.conversation.round_no
                   if self.conversation is not None else 0)
            _fname = f"{_rn}-{unit_id}.jsonl" if _rn else f"{unit_id}.jsonl"
            self._session = SessionLog(self.state_root / ".wuxing" / "sessions" /
                                       _fname)
        except Exception:
            self._session = None
        if self._session is not None and not resume_session and not continue_from:
            # 初始上下文头（resume/continue 场景：历史行已在存档中，不重复 seed）
            self._session.seed(self._messages)
        # L3-4：选择来源元数据（记忆引导 vs 回退——评测归因）
        try:
            _spec = llm.spec() if hasattr(llm, "spec") else llm.name()
        except Exception:
            _spec = llm.name()
        self._mem_meta = {"picked_by_brain": bool(
            getattr(llm, "_picked_by_brain", False)), "spec": _spec}
        # P1 T1：usage 段快照（B12：thread-local——并发碎片各记各的，不串入；
        # 假 LLM 差分回退——UsageTracker 封装）
        from wuxing.usage_tracker import UsageTracker
        self._usage = UsageTracker(llm)
        self._usage_snap = self._usage.snapshot()
        return [], []

    def _verify_deps_missing(self) -> bool:
        """M1-1：verify 待验路径全部缺失（不存在文件）——机制自动兜底判定。"""
        paths = [p for p in (self._cur_params or {}).get("paths", "").splitlines()
                 if p.strip()]
        if not paths:
            return False
        for p in paths:
            if self.ws.read(p) is not None:
                return False  # 任一存在 → 交还模型判定
        return True

    @staticmethod
    def _accepts_tools(fn) -> bool:
        """签名预检：fn 是否接 tools 参数（无法预检 → 默认支持）。"""
        try:
            import inspect
            params = inspect.signature(fn).parameters
            return "tools" in params or any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in params.values())
        except (TypeError, ValueError):
            return True  # 无法预检（C 实现等）
