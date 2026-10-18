"""预算护栏（LLM 接入降成本方案 #7）：shape_task 每预算周期调用上限，超限抛 BudgetExceeded。

组合方式：CachedLLM(BudgetGuard(RealLLM)) —— 缓存命中不消耗预算（预算=真实 API 调用）；
调用方捕获 BudgetExceeded 后回退（缓存 / 规则表 / mock 模板）。
"""
from golden_ratio.llm import LLMClient


class BudgetExceeded(Exception):
    """每预算周期的真实 LLM 调用次数已超限。"""


class BudgetGuard(LLMClient):
    def __init__(self, inner, max_calls=3):
        self.inner = inner
        self.max_calls = max_calls
        self.calls = 0

    def reset(self):
        self.calls = 0

    def _shape_or_raise(self):
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"预算超限: 已调用 {self.calls}/{self.max_calls} 次")
        self.calls += 1

    def shape_task(self, task_text):
        self._shape_or_raise()
        return self.inner.shape_task(task_text)

    def merge_nodes(self, node_infos):
        return self.inner.merge_nodes(node_infos)

    def rebalance_suggest(self, fragment_info):
        return self.inner.rebalance_suggest(fragment_info)

    def score_keys(self, tokens):
        return self.inner.score_keys(tokens)
