"""Runner 工具执行子系统（骨架分期 P7/F-3f：自 runner.py 提取的方法组）。

来源：`wuxing/runner.py`（2026-10-06 迁移；方法体逐字节保持）。
理由：F-3 巨型文件分期——工具调用解析/并发执行面落隔离模块（mixin 组合）；**不得 import engine**（守卫）。
"""
import time

from wuxing.runner_support import (
    _KV_RE,
    _TOOLCALL_RE,
    MAX_PARALLEL_TOOLS,
    _is_side_effect_free,
    _is_test_path,
    _test_run_attempted,
    _test_run_passed,
)


class RunnerToolsMixin:
    def _exec_toolcalls(self, out: str, whitelist: list, logs: list,
                       unit_id: str = ""):
        """文本协议（旧路径，deprecated）：解析 TOOLCALL 行。

        B6（审查）：unit_id 透传——文本协议路径下 delegate 子任务的
        溯源父链不得断链（此前硬编码 ""——provenance parent 丢失）。
        """
        for line in out.splitlines():
            m = _TOOLCALL_RE.match(line.strip())
            if not m:
                continue
            name, rest = m.group(1), m.group(2)
            kwargs = {k: v for k, v in _KV_RE.findall(rest)}
            logs.extend(self._execute_toolcall(
                {"name": name, "arguments": kwargs}, whitelist,
                unit_id=unit_id))

    def _execute_tool_calls_batch(self, calls: list, whitelist: list,
                                  logs: list, unit_id: str = "") -> None:
        """M1-4：工具级并行执行（CPU 速度主轴——纯软件，零硬件门槛）。

        - 无副作用工具（权限声明只读：read=True 且其余全假——X5/E3-1）→ 组内
          线程并发（IO 等待重叠——墙钟摊薄；#3：worker 上限 min(batch,
          max_parallel_tools)）
        - 有副作用工具（write/bash/delegate/网络类）→ 按模型发出顺序串行
        - **独占屏障（D2/E3-1）**：写/执行调用构成排序屏障——写前读批先完成、
          写后读批重开一批（读批不得跨越写重排；执行序=模型调用序）
        - 回填顺序 = 调用顺序（并发完成但日志按序 extend——消息语义稳定）
        """
        from concurrent.futures import ThreadPoolExecutor
        batch = []

        def _tool_limit() -> int:
            try:
                val = int(getattr(self.cfg, "max_parallel_tools", 8))
            except (TypeError, ValueError):
                val = 8
            return max(1, min(val, MAX_PARALLEL_TOOLS))

        def flush():
            if not batch:
                return
            if len(batch) == 1:
                logs.extend(self._execute_toolcall(batch[0], whitelist, unit_id))
            else:
                with ThreadPoolExecutor(max_workers=min(len(batch),
                                                        _tool_limit())) as ex:
                    futs = {i: ex.submit(self._execute_toolcall, tc, whitelist,
                                          unit_id)
                            for i, tc in enumerate(batch)}
                    for i in sorted(futs):
                        logs.extend(futs[i].result())
            batch.clear()

        for tc in calls:
            name = tc.get("name", "")
            if _is_side_effect_free(name, self.tools):
                batch.append(tc)
            else:
                flush()
                logs.extend(self._execute_toolcall(tc, whitelist, unit_id))
        flush()

    def _pause_for_answer(self, unit_id: str, domain_id: str, artifacts: list,
                          logs: list, last_reply: str = ""):
        """E2-5（A10）：提问挂起收尾（fail-closed——无答复不继续跑）。

        调用时机：本轮工具批执行完 + 历史已写入之后（SessionLog 含 [ask] 标记——
        答复续跑可配对）；挂起槽消费；单元状态置 waiting。
        """
        from wuxing.protocols import UnitResult
        pq = dict(getattr(self, "_ask_pending", None) or {})
        self._ask_pending = None    # 消费（答复后由 engine 以 resume 注入续跑）
        self._transition("waiting", unit_id, domain_id)
        if self._session is not None:
            self._session.append(round_no=self._rounds, state="needs_answer",
                                 messages=[], status="needs_answer")
        return UnitResult(unit_id=unit_id, domain_id=domain_id,
                          status="needs_answer", artifacts=artifacts, logs=logs,
                          reply=last_reply,
                          error="ask: waiting for user answer",
                          pending_question=pq)

    def _note_evidence(self, name, args, status, content, unit_id: str = "",
                       via: str = "model") -> None:
        """O3：证据累计统一入口（模型直调 + Code Mode 脚本内调同源）。

        write/read 物证 + 测试文件动态触发运行要求（C2b）；bash 运行物证维持
        pytest 口径（C2c 扩展为 _test_run_passed）。
        """
        if status != "ok":
            return
        if name in ("write_artifact", "write_file"):
            self._write_ok = True
            p = (args or {}).get("path")
            # S-C：真实交付物路径（工具参数即真相——无需改协议）
            if p and p not in self._deliverables:
                self._deliverables.append(p)
            if (p and getattr(self, "_current_domain_id", "") == "execute"
                    and not getattr(self, "_require_run", False)
                    and _is_test_path(p)):
                self._require_run = True
                if self.trace is not None:
                    self.trace.log("run_required", unit_id,
                                   self._current_domain_id,
                                   source="test_file", path=str(p))
        elif name in ("read_dependency", "read_file"):
            self._read_ok = True
        elif name in ("bash", "run_tests"):
            # RT5/O3-C2c：运行物证——pytest 或 unittest 通过输出（不依赖
            # require_run：晚触发的运行要求可复用先前成功运行）；
            # O2-1：run_tests 与 bash 同源计入（验收域实跑能力）
            cmd = str((args or {}).get("command") or "")
            if not getattr(self, "_run_attempted", False) \
                    and _test_run_attempted(cmd):
                self._run_attempted = True  # S1-B：尝试位（不论通过与否）
            if not getattr(self, "_run_ok", False) and _test_run_passed(cmd, content):
                self._run_ok = True
                if self.trace is not None:
                    self.trace.log("run_evidence", unit_id,
                                   getattr(self, "_current_domain_id", ""),
                                   via=via)

    def _execute_toolcall(self, tc: dict, whitelist: list,
                          unit_id: str = "") -> list:
        """统一工具执行（P5）：白名单校验 → guard → 执行；结果结构化（阶段 3）。

        M1-4：返回日志行列表（不再直接 append——批量执行按序回填）。
        - 白名单外：记录 _blocked_tools（不收敛阻断——LLM 可继续下轮）
        - blocked（guard 拦截）：同上
        - error（执行异常）：logs 语义化（修复器可归因）
        - ok：内容入 logs
        统一入口做重复提醒（DSH repeat-tool-reminder 参考）：连拦/连执同参数都算空转。
        unit_id：当前父单元（3c——delegate 溯源父子链动态注入）。
        """
        lines = []
        name = tc.get("name", "")
        kwargs = tc.get("arguments", {}) or {}
        # 3c：delegate 溯源——父单元 id 动态注入
        if name == "delegate":
            delegate = self.tools.get("delegate")
            if delegate is not None:
                delegate._parent_unit_id = unit_id
                # E3-2（P1/H3）：Subagent 事件通道（与父单元链同注入惯例）
                delegate._emit_event = self.emit_event
        # P4 T1：工具执行状态（可观测）
        self._transition("tool_executing", unit_id=unit_id,
                         domain_id=getattr(self, "_current_domain_id", ""))
        # #3（2026-09-11 报告 #6）：单元内同名同参计数——第 3 次提醒一次
        # （原「连续」检测漏掉跨轮非连续空转：45.4% 重复率主体；提示不阻断）
        # 六轮审查 A1：计数键用完整参数指纹（结构化参数安全——不得做不可哈希键）
        key = (name, self._args_key(kwargs))
        counts = getattr(self, "_tool_key_counts", None)
        if counts is None:
            counts = self._tool_key_counts = {}
        cnt = counts.get(key, 0) + 1
        counts[key] = cnt
        if cnt == 3:
            lines.append(f"[warn] 重复工具调用 {name}（单元内第 3 次，参数相同）"
                         f"——若未收敛请更换策略")
        allowed = {t.name() for t in whitelist}
        if name not in allowed:
            self._blocked_tools.append(name)
            lines.append(f"[guard] blocked tool: {name} (not in whitelist)")
            if self.trace is not None:
                self.trace.log("tool_call", unit_id, self._current_domain_id,
                               round=self._rounds, name=name,
                               arg_hash=self._arg_hash(kwargs), status="blocked",
                               latency_ms=0, reason="not-in-whitelist",
                               **self._trace_fields())
            return lines
        # E2-5（A10）：ask_user 挂起语义——同批独占 + 每单元上限（前置拦截）
        if name == "ask_user":
            from wuxing.tools.ask_tool import MAX_ASKS_PER_UNIT
            if getattr(self, "_ask_pending", None) is not None:
                lines.append("[tool:error] ask_user: 同一批仅允许一个提问"
                             "（已有待答问题）")
                return lines
            if int(getattr(self, "_ask_seq", 0) or 0) >= MAX_ASKS_PER_UNIT:
                lines.append(f"[tool:error] ask_user: 本单元提问已达上限"
                             f"（{MAX_ASKS_PER_UNIT} 次）——请基于现有信息继续或收尾")
                return lines
        # A4：Code Mode——执行前注入上下文（仿 delegate 惯例；守卫链不绕）
        if name == "run_script":
            _rs = self.tools.get("run_script")
            if _rs is not None and hasattr(_rs, "set_context"):
                _rs.set_context(
                    registry=self.tools, whitelist=allowed, trace=self.trace,
                    unit_id=unit_id,
                    domain_id=getattr(self, "_current_domain_id", ""),
                    on_inner_call=lambda n, a, s, c: self._note_evidence(
                        n, a, s, c, unit_id=unit_id, via="code_mode"))
        t0 = time.time()
        res = self.tools.execute(name, **kwargs)
        latency_ms = int((time.time() - t0) * 1000)
        if self.trace is not None:
            route = {}
            if name in ("bash", "run_tests"):
                _t = self.tools.get(name)
                if _t is not None and hasattr(_t, "route_info"):
                    route = _t.route_info()
            # BOX-M3：阻断类结果带 reason 维度（命令审计可归因）
            _block_reason = ({"reason": str(res.error)[:200]}
                             if res.status == "blocked" and res.error else {})
            self.trace.log("tool_call", unit_id, self._current_domain_id,
                           round=self._rounds, name=name,
                           arg_hash=self._arg_hash(kwargs), status=res.status,
                           latency_ms=latency_ms, **route, **_block_reason,
                           **self._trace_fields())
        if res.status == "error":
            lines.append(f"[tool:error] {name}: {res.error}")
            # L2-4（FC 层3）：失败归因 → 指令级修正提示回填（模型可见——非文案空转）
            from wuxing.repairer import classify_failure, repair_hint
            _cls = classify_failure(res.error)
            _hint = repair_hint(_cls, res.error)
            lines.append(f"[repair] 修正指令：{_hint['hint']}")
        elif res.status == "needs_answer":
            # E2-5（A10）：挂起登记（runner 在批后统一停轮 → needs_answer）
            # O2-2（P1 T6）：泛化——工具可自带 pending_questions/pending_meta
            # （浏览器回环确认）；缺省回退 ask_user.last_questions（既有行为）
            questions = list(res.pending_questions or [])
            meta = dict(res.pending_meta or {})
            if not questions:
                tool = self.tools.get("ask_user")
                questions = list(getattr(tool, "last_questions", None) or [])
            seq = int(getattr(self, "_ask_seq", 0) or 0) + 1
            self._ask_seq = seq
            qid = f"ask-{unit_id}-{seq}"
            self._ask_pending = {
                "unit_id": unit_id,
                "domain_id": getattr(self, "_current_domain_id", ""),
                "question_id": qid,
                "questions": questions,
                "kind": str(meta.get("kind", "") or ""),
                "meta": meta,
            }
            if self.trace is not None:
                self.trace.log("question_asked", unit_id,
                               getattr(self, "_current_domain_id", ""),
                               question_id=qid, questions=questions,
                               kind=str(meta.get("kind", "") or ""),
                               surface="question",
                               source=("mechanism" if str(
                                   meta.get("kind", "") or "") else "model"),
                               round=self._rounds, **self._trace_fields())
            lines.append(f"[ask] {qid} | {res.content}")
        elif res.status == "blocked":
            self._blocked_tools.append(name)
            lines.append(f"[guard] blocked: {name}: {res.error}")
            self._emit_safety_blocked(unit_id, name, kwargs, res.error)
        else:
            lines.append(f"[tool] {name}: {res.content}")
        # P0 T3（S5）：物证累计——O3：统一入口（模型直调 + Code Mode 脚本内调同源）
        if res.status == "ok" and name == "todo_write":
            # E2-5（L5）：清单快照入 trace（append-only；全量——审计价值）
            _todo = self.tools.get("todo_write")
            if self.trace is not None and _todo is not None:
                self.trace.log(
                    "todo_write", unit_id,
                    getattr(self, "_current_domain_id", ""),
                    round=self._rounds,
                    items=list(getattr(_todo, "items", []) or []),
                    **self._trace_fields())
        elif res.status == "ok":
            self._note_evidence(name, kwargs, res.status, str(res.content or ""),
                                unit_id=unit_id)
        # 3c 预算继承：delegate 子任务调用数计入父单元（总成本有界）
        child_calls = getattr(res, "child_calls", 0)
        if child_calls:
            self._calls += child_calls
        return lines
