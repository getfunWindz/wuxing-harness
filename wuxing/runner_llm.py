"""Runner LLM 调用/用量子系统（骨架分期 P7/F-3f：自 runner.py 提取的方法组）。

来源：`wuxing/runner.py`（2026-10-06 迁移；方法体逐字节保持）。
理由：F-3 巨型文件分期——LLM 调用与用量面落隔离模块（mixin 组合）；**不得 import engine**（守卫）。
"""
import logging
import time

from wuxing.runner_support import _REASONING_DELTA_CAP, _ReasoningDeltaThrottle

logger = logging.getLogger(__name__)


class RunnerLlmMixin:
    def _chat_with_tools(self, llm, on_delta=None):
        """G7 v2（E2-2）：LLM 调用包装——上下文溢出 → 配对安全裁剪 + 一次重试。

        溢出为确定性错误（非 provider 抖动）：裁剪装配消息后重试一次；
        仍失败/无可裁 → 原异常上行（既有 provider 失败路径不变）。
        """
        try:
            return self._chat_once(llm, on_delta=on_delta)
        except Exception as exc:
            from wuxing.repairer import is_context_overflow_error
            if not is_context_overflow_error(exc):
                raise
            from wuxing.context_budget import trim_oldest_chunks
            from wuxing.context_preview import estimate_tokens
            est_total = sum(estimate_tokens(str(m.get("content", "")))
                            for m in self._messages)
            target = max(1024, est_total // 2)
            out_msgs, removed, chars = trim_oldest_chunks(
                self._messages, target, estimate_tokens)
            if not removed:
                raise
            self._messages = out_msgs
            if self.trace is not None:
                self.trace.log("context_overflow_recovery", "", "",
                               chunks=removed, chars=chars, target=target,
                               **self._trace_fields())
            return self._chat_once(llm, on_delta=on_delta)

    def _provider_messages(self) -> list:
        """H6（E3-5）：provider 入参剥除内部键（`_` 开头，如 `_call_time`）。

        调用载荷内容/顺序不变——仅剥离内部标记（防内部键泄漏给适配器）。
        """
        out = []
        for m in self._messages:
            if isinstance(m, dict) and any(str(k).startswith("_") for k in m):
                m = {k: v for k, v in m.items() if not str(k).startswith("_")}
            out.append(m)
        return out

    def _chat_once(self, llm, on_delta=None):
        """F1 冒烟修复：原生 tools 接线——LLM 必须获得白名单工具 schema。

        真 LLM 冒烟实证：DeepSeek 从不调用工具（代码写进文本）——runner 此前
        调 chat(messages) 未传工具定义。
        B10（审查）：回退判定改为**签名预检**——仅当 chat 签名确实不支持
        tools 参数才降级（否则 provider 内部 TypeError bug 被静默吞掉——
        降级重调放大故障且无声）。
        Task 1-3（思维链流式）：provider 支持 chat_stream 且有增量消费方时优先
        流式；任何异常回退 chat()——流式仅增量增强，不破坏非流式路径。
        """
        stream = getattr(llm, "chat_stream", None)
        msgs = self._provider_messages()  # H6：内部键剥除（`_call_time`）
        _stream_ok = True
        _cap = getattr(llm, "supports_stream", None)
        if callable(_cap):
            try:
                _stream_ok = bool(_cap())
            except Exception as exc:
                # 能力探测失败 → 维持默认尝试（观测不阻断）
                logger.debug("supports_stream 探测失败（按支持处理）：%s", exc)
        if on_delta is not None and callable(stream) and _stream_ok:
            try:
                if self._accepts_tools(stream):
                    return stream(msgs, tools=self._tool_schemas,
                                  on_delta=on_delta)
                return stream(msgs, on_delta=on_delta)
            except Exception as exc:  # 韧性：流式失败回退非流式
                from wuxing.repairer import is_context_overflow_error
                if is_context_overflow_error(exc):
                    raise  # 溢出：同消息的非流式调用必然同样失败——交恢复包装
                logger.warning("chat_stream 异常，回退 chat（%s）：%s",
                               type(exc).__name__, exc)
        if not self._accepts_tools(llm.chat):
            return llm.chat(msgs)
        return llm.chat(msgs, tools=self._tool_schemas)

    def _chat_traced(self, llm, unit_id: str, domain_id: str):
        """L1-1：LLM 轮次 trace（latency + 本轮 usage 增量真值）。

        usage 增量：游标差分（_usage_cursor 前移——并发碎片各 runner 独立游标）。
        缓存命中轮不调用（无 llm_call 事件——trace=实际发生的调用）。
        2026-09-11：思维链（reasoning）落 llm_reasoning 事件（观测增强——
        DeepSeek-flash thinking；不参与消息构造）。
        2026-10-01 专项 Task 2：流式 provider 逐段发 unit_reasoning_delta
        （节流合并 + 10k 封顶；有事件消费方时才启用流式）。
        """
        t0 = time.time()
        snap = self._usage.snapshot()
        on_delta = None
        throttle = None
        if self.emit_event is not None and callable(
                getattr(llm, "chat_stream", None)):
            sent = {"n": 0, "truncated": False}

            def _emit_delta(text: str) -> None:
                from wuxing.events import UnitReasoningDelta
                self.emit_event(UnitReasoningDelta(
                    unit_id=unit_id, domain_id=domain_id,
                    round=int(self._rounds or 0), text=text))

            throttle = _ReasoningDeltaThrottle(_emit_delta)

            def _on_delta(kind: str, text: str) -> None:
                if kind != "reasoning" or not text:
                    return
                if sent["n"] >= _REASONING_DELTA_CAP:
                    if not sent["truncated"]:
                        sent["truncated"] = True
                        _emit_delta("…（思维链过长，已截断）")
                    return
                clipped = str(text)[:_REASONING_DELTA_CAP - sent["n"]]
                sent["n"] += len(clipped)
                throttle.push(clipped)

            on_delta = _on_delta
        try:
            out = self._chat_with_tools(llm, on_delta=on_delta)
        finally:
            if throttle is not None:
                throttle.flush()
        latency = int((time.time() - t0) * 1000)
        _rc = ""
        _take_rc = getattr(llm, "_take_reasoning", None)
        if callable(_take_rc):
            try:
                _rc = str(_take_rc() or "")
            except Exception:
                _rc = ""
        used = self._usage.since(snap)
        if used:
            # CH 口径（用户裁决 2026-10-02）：记录最近一次请求 usage（供任务级）
            from wuxing.usage_tracker import UsageTracker
            self._last_call_usage = UsageTracker.aggregate(used)
            self._last_call_ts = time.time()
        if self.trace is not None:
            # B12：thread-local 段（本线程调用序列——不串入并发碎片）
            from wuxing.usage_tracker import trace_llm_call
            trace_llm_call(self.trace, unit_id, domain_id, self._rounds,
                           latency, used,
                           extra=self._trace_fields())
            if _rc:
                self.trace.log("llm_reasoning", unit_id, domain_id,
                               round=self._rounds, text=_rc[:3000],
                               **self._trace_fields())
        if _rc and self.emit_event is not None:
            # R4-3：思维链进事件流（壳渲染「思考块」；文本封顶——事件体积可控）
            from wuxing.events import UnitReasoning
            self.emit_event(UnitReasoning(unit_id=unit_id, domain_id=domain_id,
                                          round=int(self._rounds or 0),
                                          text=_rc[:10000]))
        return out

    def _unit_metrics(self, llm) -> dict:
        """P1 T1：单元 usage 汇总（B12：thread-local 段——并发碎片各记各的）。

        CH 口径（用户裁决 2026-10-02）：附最近一次请求 usage（usage_latest
        + 时间戳）——供任务级取「最近一次有效请求」的命中率。
        """
        from wuxing.usage_tracker import UsageTracker, split_calls
        used = self._usage.since(getattr(self, "_usage_snap", 0))
        m = {"llm_calls": len(used),
             "usage": UsageTracker.aggregate(used)}
        # E0-6：单元级 CH 三分（首调用/延续 + miss 归因）
        m["ch_split"] = split_calls(used)
        last = getattr(self, "_last_call_usage", None)
        if isinstance(last, dict):
            m["usage_latest"] = dict(last)
            m["usage_latest_ts"] = getattr(self, "_last_call_ts", None)
        return m

    def _shared_record(self, unit_id, params, result):
        """L3：碎片完成后记录共享三要素（确定性提取——失败也记录供循迹）。"""
        try:
            if self.shared is not None:
                self.shared.record(result, params.get("fragment_key", ""), ws=self.ws)
        except Exception as exc:
            logger.debug("共享记录写入失败（不阻断）：%s", exc)
