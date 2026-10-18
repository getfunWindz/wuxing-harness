"""Runner 历史/压缩/记录子系统（骨架分期 P7/F-3f：自 runner.py 提取的方法组）。

来源：`wuxing/runner.py`（2026-10-06 迁移；方法体逐字节保持）。
理由：F-3 巨型文件分期——历史/压缩/记录/事件面落隔离模块（mixin 组合）；**不得 import engine**（守卫）。
"""
import logging
import re
import time

from wuxing.protocols import UnitResult
from wuxing.runner_support import _prepare_tool_result

logger = logging.getLogger(__name__)


class RunnerRecordsMixin:
    def _append_round_history(self, llm_text: str, tool_msgs: list,
                              unit_id: str = ""):
        """P0 闭环（S1）：把本轮 LLM 文本 + 工具执行结果追加进消息历史。

        工具结果与 LLM 文本顺序 = 对话自然序：模型先说，工具随后执行，
        下一轮模型看到：自己上轮输出 + 实际工具结果（可据此继续/收敛）。
        G6：压缩前全文经 on_truncate 落盘（.wuxing/truncated——截断≠丢弃）。
        """
        # 空文本不入历史（跨 provider 兼容——E3-4 真跑 2026-10-04）：纯工具轮
        # 模型无正文 → 若追加空 content，Moonshot 严格拒（400 "must not be empty"）；
        # 工具结果仍是完整信号（引擎不回声 tool_calls 结构）。
        if str(llm_text or "").strip():
            self._messages.append({"role": "user", "content": llm_text})
        if tool_msgs:
            from wuxing.context import compress_tool_results
            # PE-1：工具结果边界标记（注入防护——不可信内容与指令区分离 + source 溯源）
            # SEC1：先净化（伪边界/隐形字符/注入模式）再封装；findings 落 trace
            _sanitize_on = self._sanitize_enabled()
            wrapped = []
            findings_all: list = []
            for m in tool_msgs:
                w, f = _prepare_tool_result(m, sanitize=_sanitize_on)
                wrapped.append(w)
                findings_all.extend(f)
            if findings_all:
                # C2（E0-4）：trace 负载——真实计数 + 模式名/样本（设计 §2.4）
                boundary = sum(int(f.get("count") or 0) for f in findings_all
                               if f.get("kind") == "boundary")
                invisible = sum(int(f.get("count") or 0) for f in findings_all
                                if f.get("kind") == "invisible")
                pats = [f for f in findings_all if f.get("kind") == "pattern"]
                names: list = []
                samples: list = []
                for f in pats:
                    nm = str(f.get("name") or "")
                    if nm and nm not in names:
                        names.append(nm)
                    smp = str(f.get("sample") or "")
                    if smp and smp not in samples and len(samples) < 3:
                        samples.append(smp)
                self._trace_compaction(unit_id, "sanitize",
                                       boundary=boundary, invisible=invisible,
                                       pattern=len(pats), patterns=names,
                                       samples=samples)
            compressed = compress_tool_results(
                [{"role": "user", "content": "\n".join(wrapped)}],
                max_chars=getattr(self, "_max_tool_chars", 8192),
                tool_limits=getattr(self.cfg, "context_tool_limits", None),
                on_truncate=self._make_truncate_dumper(unit_id))
            self._messages.append(compressed[0])
            # O2-2 P2：旧快照替换（投影层 keep-latest；存档 delta 零改写）
            from wuxing.snapshot_supersede import supersede_old_snapshots
            _superseded = supersede_old_snapshots(self._messages)
            if _superseded and self.trace is not None:
                self.trace.log("snapshot_superseded", unit_id, "",
                               replaced=_superseded)

    def _make_truncate_dumper(self, unit_id: str):
        """G6：截断全文落盘回调（压缩前全文 → .wuxing/truncated；失败不阻断）。"""
        def _dump(full_text):
            from wuxing.truncate_dump import dump_truncated
            path = dump_truncated(self.ws.root, full_text, unit=unit_id)
            if path and self.trace is not None:
                self.trace.log("truncate_dump", unit_id, "",
                               path=path, chars=len(full_text))
            return path
        return _dump

    def _emit_user_prompt_submit(self, unit_id: str, domain_id: str,
                                 prompt: str) -> None:
        """E3-2（P1/H5）：UserPromptSubmit——钩子可返回 {"additional_context": str}。

        收集后尾插一条用户消息（前缀不变——缓存友好）；上限 2000 字符；
        trace `extension_user_context`（count/chars）；发射/收集失败不阻断。
        """
        from wuxing.events import UserPromptSubmit
        ev = UserPromptSubmit(unit_id=str(unit_id), domain_id=str(domain_id),
                              prompt=str(prompt or ""))
        if self.emit_event is not None:
            try:
                self.emit_event(ev)
            except Exception as exc:
                logger.debug("UserPromptSubmit 事件发射失败（不阻断）：%s", exc)
        if self.hook_collect is None:
            return
        try:
            results = self.hook_collect(ev)
        except Exception as exc:
            logger.debug("UserPromptSubmit 收集失败（不阻断）：%s", exc)
            return
        parts: list = []
        for res in (results or ()):
            if isinstance(res, dict):
                text = str(res.get("additional_context") or "").strip()
                if text:
                    parts.append(text)
        if not parts:
            return
        text = "\n\n".join(parts)[:2000]
        target = getattr(self, "_messages", None)
        if target is None:
            return
        target.append({"role": "user", "content": "[扩展上下文]\n" + text})
        if self.trace is not None:
            try:
                self.trace.log("extension_user_context", unit_id, domain_id,
                               count=len(parts), chars=len(text))
            except Exception as exc:
                logger.debug("扩展上下文注入事件记录失败（不阻断）：%s", exc)

    def _emit_compact(self, cls_name: str, unit_id: str, **fields) -> None:
        """E3-2（P1/H4）：压缩生命周期事件发射（emit_event 缺省零行为）。"""
        if self.emit_event is None:
            return
        try:
            from wuxing import events as _events
            ev = getattr(_events, cls_name)(
                unit_id=str(unit_id),
                domain_id=str(getattr(self, "_current_domain_id", "") or ""),
                **fields)
            self.emit_event(ev)
        except Exception as exc:
            logger.debug("压缩事件发射失败（不阻断）：%s", exc)

    def _compact_llm_history(self, unit_id: str, trigger: int,
                             window: int = 0) -> bool:
        """G7：LLM 摘要压缩（可选链）——旧轮摘要落 compaction 行（原文零删除）。

        返回 True=已写入（自下一轮装配起生效；本轮由机械链兜底）；
        False=不可用（无会话状态/mock）/无可压缩跨度/失败（降级机械，trace 可见）。
        口径（E0-3/B2）：LLM 摘要链**仅会话路径可达**——headless CLI 无
        conversation 状态（返回 False 并落 trace reason=no_conversation，B3）；
        CLI 路径由机械链（auto_trim）承担。
        E2-2（G7 v2）：保留区以 (W−O)×16% 封顶（K2）；摘要不缩小即拒绝（B1）；
        details.files 跨压缩累计（PP5）。
        I2（v65）：读-改-写整体持有 conversation 压缩互斥；跨实例按路径协调。
        """
        state = getattr(self, "conversation", None)
        if state is None:
            # B3（E0-3）：不可达必须可观测——headless 压缩链静默 False 根因
            self._trace_compaction(unit_id, "compaction_degraded",
                                   reason="no_conversation")
            return False
        if trigger <= 0:
            return False
        with state.compaction_guard():
            # 跨实例互斥后刷新磁盘视图（另一实例可能已写入压缩行）
            state.reload()
            return self._compact_llm_history_locked(unit_id, trigger, window, state)

    def _compact_llm_history_locked(self, unit_id: str, trigger: int,
                                    window: int, state) -> bool:
        """I2：压缩读-改-写临界区（调用方必须持有 state.compaction_guard()）。"""
        try:
            spec = self.llm.spec() if hasattr(self.llm, "spec") else ""
        except Exception:
            spec = ""
        if str(spec or "").strip().lower() in ("", "mock"):
            self._trace_compaction(unit_id, "compaction_degraded",
                                   reason="mock")
            return False
        from wuxing.context_budget import effective_keep_recent
        from wuxing.context_preview import estimate_tokens
        comp = state.last_compaction()
        covered = int(comp.get("to_round") or 0) if comp is not None else 0
        keep = effective_keep_recent(self.cfg, window)
        turns = [t for t in state.turns
                 if "round" in t and not str(t.get("type") or "")
                 and not str(t.get("unit") or "")
                 and int(t.get("round") or 0) > covered]
        cut = 0
        acc = 0
        for i in range(len(turns) - 1, -1, -1):
            acc += estimate_tokens(str(turns[i].get("user_text") or ""))
            if acc > keep:
                cut = i + 1
                break
        to_compact = turns[:cut]
        if not to_compact:
            return False
        first = int(to_compact[0].get("round") or 0)
        last = int(to_compact[-1].get("round") or 0)
        from_round = int(comp.get("from_round") or first) if comp else first
        prev = str(comp.get("summary") or "") if comp is not None else ""
        src_tokens = sum(estimate_tokens(str(t.get("user_text") or ""))
                         for t in to_compact)
        # E3-2（P1/H4）：压缩尝试前事件（LLM 链；机械链投影不发射）
        self._emit_compact("PreCompact", unit_id, from_round=from_round,
                           to_round=last, source_tokens=src_tokens)
        try:
            summary = self._llm_compaction_summary(to_compact, prev)
        except Exception as e:  # 模型失败——降级机械（不阻断）
            self._trace_compaction(unit_id, "compaction_degraded",
                                   reason=f"{type(e).__name__}: {e}")
            self._emit_compact("PostCompact", unit_id, from_round=from_round,
                               to_round=last, status="degraded")
            return False
        if not summary:
            self._trace_compaction(unit_id, "compaction_degraded",
                                   reason="empty summary")
            self._emit_compact("PostCompact", unit_id, from_round=from_round,
                               to_round=last, status="degraded")
            return False
        # E2-2（B1）：摘要不缩小即拒绝（DSH 事务验证——不缩小 = 无效压缩）
        sum_tokens = estimate_tokens(summary)
        if src_tokens > 0 and sum_tokens >= src_tokens:
            self._trace_compaction(unit_id, "compaction_rejected",
                                   reason="not-shrinking",
                                   from_round=from_round, to_round=last,
                                   summary_tokens=sum_tokens,
                                   source_tokens=src_tokens)
            self._emit_compact("PostCompact", unit_id, from_round=from_round,
                               to_round=last, status="rejected",
                               summary_tokens=sum_tokens)
            return False
        # E2-2（PP5）：文件累计跟踪（上次 details ∪ 本次被压轮 artifacts）
        prev_details = (comp or {}).get("details") or {}
        files = {str(x) for x in (prev_details.get("files") or []) if str(x)}
        for t in to_compact:
            files.update(str(a) for a in (t.get("artifacts") or []) if str(a))
        row = {"type": "compaction", "from_round": from_round,
               "to_round": last, "summary": summary, "mode": "llm",
               "details": {"files": sorted(files)},
               "ts": round(time.time(), 3)}
        state.append_row(row)
        self._trace_compaction(unit_id, "compaction_written",
                               from_round=from_round, to_round=last,
                               chars=len(summary))
        self._emit_compact("PostCompact", unit_id, from_round=from_round,
                           to_round=last, status="written",
                           summary_tokens=sum_tokens)
        return True

    def _llm_compaction_summary(self, turns: list, prev: str) -> str:
        """压缩摘要（结构化；迭代携带旧摘要；失败抛错由调用方降级）。"""
        lines = []
        for t in turns:
            rnd = t.get("round", "?")
            text = str(t.get("user_text") or "")[:200]
            sm = str(t.get("summary") or "")[:120]
            lines.append(f"第{rnd}轮：{text}" + (f"（{sm}）" if sm else ""))
        body = "\n".join(lines)[:6000]
        prompt = ("以下是较早的会话轮次（更近轮次将原样保留）。请压缩为结构化"
                  "摘要：目标、已完成、结论与遗留问题。不超过 300 字，"
                  "直接输出摘要正文。\n"
                  + (f"此前摘要（需延续融合）：{prev}\n" if prev else "")
                  + "——待压缩轮次——\n" + body)
        out = self.llm.chat([{"role": "user", "content": prompt}])
        text = out if isinstance(out, str) else str(
            getattr(out, "text", None) or out or "")
        return " ".join(text.split())[:2000]

    def _trace_compaction(self, unit_id: str, event: str, **fields) -> None:
        if self.trace is not None:
            self.trace.log(event, unit_id, "", **fields)

    def _provenance_record(self, unit_id, params, domain_id, llm, status, artifacts):
        """3c 决策 C：单元溯源记录（append-only——任务→单元→产物全链可查）。"""
        if self.provenance is None:
            return
        try:
            self.provenance.record(
                unit_id=unit_id,
                parent_id=params.get("parent_unit_id", ""),
                task_text=params.get("fragment_key", ""),
                goal=params.get("goal", ""), domain=domain_id,
                model=llm.name(), status=status,
                artifacts=[a.path for a in artifacts])
        except Exception as exc:
            logger.debug("单元溯源写入失败（不阻断）：%s", exc)

    _PROGRESS_RE = re.compile(
        r"进度心跳[:：]\s*([^｜|\n]+?)"
        r"(?:\s*[｜|]\s*预计剩余[:：]\s*([^\n]+))?\s*$",
        re.MULTILINE)

    def _emit_progress_reports(self, unit_id, domain_id, out) -> None:
        """壳 P1 对齐项⑤：模型自报进度 → ProgressReport 事件（不改任务语义）。

        节奏定义权在模型（不设固定汇报定时器）；未自报则壳回退事件驱动进度。
        """
        if self.emit_event is None:
            return
        text = getattr(out, "text", out)
        if not isinstance(text, str) or not text:
            return
        try:
            from wuxing.events import ProgressReport
            for m in self._PROGRESS_RE.finditer(text):
                stage = (m.group(1) or "").strip()
                eta = (m.group(2) or "").strip()
                if not stage:
                    continue
                self.emit_event(ProgressReport(
                    unit_id=unit_id, domain_id=domain_id,
                    stage=stage[:200], eta=eta[:100]))
        except Exception as exc:
            logger.debug("进度事件发送失败（观测不阻断）：%s", exc)

    def _cancelled_unit(self, unit_id, domain_id) -> UnitResult:
        """取消结果（壳 P1 对齐项②）：留 trace 尾；不写 brain 案例（归因纪律）。"""
        if self.trace is not None:
            try:
                self.trace.log("unit_done", unit_id, domain_id,
                               status="cancelled", **self._trace_fields())
            except Exception as exc:
                logger.debug("取消单元 trace 记录失败（观测不阻断）：%s", exc)
        return UnitResult(unit_id=unit_id, domain_id=domain_id,
                          status="cancelled", error="cancelled by user")

    def _exit_failure(self) -> tuple[str, str]:
        """S1-B：失败收尾的（分类，人话文案）——机械合成，零 LLM 成本。

        前缀为 repairer.classify_failure 输入契约（budget:/stalled:），不得更改。
        """
        if "stalled" in (getattr(self, "_fail_reason", "") or ""):
            n = len(getattr(self, "_deliverables", None) or [])
            return "stalled", (
                f"stalled: 无进展早停（轮 {getattr(self, '_rounds', 0)}/"
                f"{getattr(self, '_unit_budget', 0)}，物证 {n} 件）")[:200]
        if getattr(self, "_run_attempted", False) \
                and not getattr(self, "_run_ok", False):
            n = len(getattr(self, "_deliverables", None) or [])
            return "budget", (
                f"budget: 预算耗尽——已运行测试但未通过"
                f"（物证 {n} 件，最后一次运行失败）")[:200]
        return "budget", "budget: 预算耗尽——未产出达标产物"

    def _provider_failure(self, unit_id, domain_id, artifacts, logs, llm, params, exc):
        """P15 真跑发现：provider 异常护栏——转 failed(provider 类)，不重试整个 unit。

        P14 Q4-B 归因纪律：provider 抖动（非 JSON/防护页/HTTP 4xx/5xx）是环境问题
        不是模型质量问题——classify_failure 归为 provider → 智脑不写入失败案例（防学习污染）。
        """
        error = f"provider: {type(exc).__name__}: {str(exc)[:200]}"
        res = UnitResult(unit_id=unit_id, domain_id=domain_id, status="failed",
                         artifacts=artifacts, logs=logs, error=error,
                         failure_class="provider")
        # L1-1：provider 失败也留 trace 尾（评测原料——失败样本）
        if self.trace is not None:
            self.trace.log("unit_done", unit_id, domain_id, status="failed",
                           verdict_fail=False, provider_error=True,
                           model=(llm.name() if hasattr(llm, "name") else "?"),
                           **self._trace_fields())
        self._brain_record(unit_id, domain_id, llm, success=False, error=error,
                           logs=logs, fragment_key=params.get("fragment_key"))
        return res

    def _brain_record(self, unit_id, domain_id, llm, success: bool, error: str = "",
                      logs: list | None = None, fragment_key: str | None = None):
        """P14 Q4-B 分类归因 + 三级参照表（2026-09-06）：收集常开——按粒度+完成度分级。

        成功：粒度命中 [0.382,0.618] → high；其余 → normal；失败 → low。
        """
        if self.brain_memory is None:
            return
        key = fragment_key or unit_id  # 无碎片文本时回退 unit_id（兼容旧行为）
        spec = getattr(llm, "spec", lambda: llm.name())()  # 鸭子类型容错（测试自定义 llm 无 spec）
        if success:
            from wuxing.llm.brain import classify_tier
            tier = classify_tier(True, getattr(self, "_cur_params", {}).get("granularity"))
            self.brain_memory.record(key=key, domain=domain_id, model=llm.name(),
                                     success=True, spec=spec, tier=tier)
            return
        # failed：分类归因
        try:
            from wuxing.repairer import classify_failure
            cls = classify_failure(error or "")
        except Exception:
            cls = "unknown"
        # 预算耗尽的根因判定：logs 有 LLM 输出但未收敛 = 契约问题（归因模型）
        llm_output_but_no_converge = cls == "budget" and len(logs) > 0
        if cls in ("contract", "unknown") or llm_output_but_no_converge:
            self.brain_memory.record(key=key, domain=domain_id, model=llm.name(),
                                     success=False, spec=spec)
