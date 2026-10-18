"""LLM 协议层（Q15 seam：本地/真LLM 无差别）。"""
import threading
import time

from wuxing.protocols import LlmProvider


class BaseLlmProvider(LlmProvider):
    """基类：call_count 记账 + 通用退避重试（P12 韧性——共享逻辑）。

    _retry_with_backoff(fn)：
      - 重试 max_retries 次（指数退避 1s/2s/4s…——防中转站防护页）
      - 任何异常都重试（provider 抖动/网络/非 JSON）
      - 重试耗尽 → 重新抛最后异常（明确失败）
    """
    def __init__(self, max_retries: int = 4):
        self.call_count = 0
        self.max_retries = max_retries
        # P1 T1：usage 真值历史（债 1——服务端缓存命中可度量）
        # 每条 = 一次成功调用的标准化 usage：{input, output, cache_read, cache_write}
        self.usage_history = []
        self._usage_lock = threading.Lock()  # B12：历史 list 并发 append 互斥
        # B12（审查）：并发 usage 隔离——共享 list 快照差分在并发碎片下
        # 串入对方调用（指标失真）；thread-local 段：各线程各记各的（无锁无竞态）
        self._tl = threading.local()

    def _usage_snapshot(self) -> int:
        """线程内 usage 段起点（并发安全——thread-local 计数）。"""
        return getattr(self._tl, "count", 0)

    def _take_usage_since(self, snap: int) -> list:
        """线程内 usage 段 [snap, now)——本线程调用序列（不串入他线程）。"""
        calls = getattr(self._tl, "calls", [])
        return calls[snap:]

    def _record_reasoning(self, text) -> None:
        """思维链记录（2026-09-11 观测增强）：线程内暂存最近一次推理文本。

        DeepSeek-flash 为 thinking 模型（reasoning_content）——观测层原料，
        不参与消息构造（不改变模型输入/缓存前缀）。
        """
        self._tl.reasoning = str(text or "")

    def _take_reasoning(self) -> str:
        """取回并清空本线程最近一次推理文本（无则空串——不跨轮串扰）。"""
        text = getattr(self._tl, "reasoning", "")
        self._tl.reasoning = ""
        return text

    def name(self):
        return self.__class__.__name__

    def _record_usage(self, usage: dict | None):
        """usage 标准化（容错）：真值缺失/异常 → 0（不崩溃——度量是观测不是生命线）。

        B12：历史 list 加锁 append（他线程可读快照）；thread-local 段同步记录
        （本线程调用序列——running 线程内读取无需锁）。
        """
        std = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        if isinstance(usage, dict):
            for k in std:
                try:
                    std[k] = int(usage.get(k, 0) or 0)
                except (TypeError, ValueError):
                    std[k] = 0
            # DeepSeek 官方字段（可选）：cache_miss 直接来自 API（非减法）
            if usage.get("cache_miss") is not None:
                try:
                    std["cache_miss"] = int(usage["cache_miss"])
                except (TypeError, ValueError):
                    # usage 字段非法 → 跳过该字段（用量统计尽力而为）
                    pass
            # 思维链 token 数（thinking 模型 completion_tokens_details）
            if usage.get("reasoning_tokens") is not None:
                try:
                    std["reasoning_tokens"] = int(usage["reasoning_tokens"])
                except (TypeError, ValueError):
                    # usage 字段非法 → 跳过该字段（用量统计尽力而为）
                    pass
        with self._usage_lock:
            self.usage_history.append(std)
        # C7 修复（2026-09-11 审查）：thread-local 列表直接 append——旧实现
        # 每次 record 全量拷贝列表（O(n²)）仅因 thread-local 单线程访问，无必要
        calls = getattr(self._tl, "calls", None)
        if calls is None:
            calls = self._tl.calls = []
        calls.append(std)
        self._tl.count = getattr(self._tl, "count", 0) + 1

    @staticmethod
    def _non_retryable(exc) -> bool:
        """B2（技术债收口 2026-09-12）：不可重试的 HTTP 4xx（401/403/404 等）
        ——除 408（超时）/429（限流）外不白耗退避时间。"""
        resp = getattr(exc, "response", None)
        code = getattr(resp, "status_code", None)
        if code is None:
            code = getattr(exc, "status_code", None)
        return isinstance(code, int) and 400 <= code < 500 \
            and code not in (408, 429)

    def _retry_with_backoff(self, fn):
        last_exc = None
        for attempt in range(self.max_retries + 1):
            self.call_count += 1
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if self._non_retryable(exc):
                    break  # 不可重试 4xx——直接上抛
                if attempt < self.max_retries:
                    time.sleep(1.0 * (2 ** attempt))  # 1s/2s/4s...
        raise last_exc
