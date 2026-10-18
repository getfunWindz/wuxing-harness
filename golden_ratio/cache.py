"""输出缓存（LLM 接入降成本方案 #1：相同/相似任务文本的 DAG 输出缓存）。

CachedLLM 包装任意 LLMClient（Mock/真 LLM 一视同仁），只缓存 shape_task（主成本项）；
命中返回深拷贝，防调用方修改污染缓存；容量满时逐出最旧（FIFO）。
"""
import copy

from golden_ratio.llm import LLMClient


class CachedLLM(LLMClient):
    def __init__(self, inner, max_entries=1000):
        self.inner = inner
        self._cache = {}
        self._order = []
        self.max_entries = max_entries
        self.hits = 0
        self.misses = 0

    def _key(self, task_text):
        """任务文本规范化：空白归一 + 英文小写（中文不区分大小写）。"""
        return " ".join(str(task_text).split()).lower()

    def shape_task(self, task_text):
        key = self._key(task_text)
        if key in self._cache:
            self.hits += 1
            return copy.deepcopy(self._cache[key])
        self.misses += 1
        out = self.inner.shape_task(task_text)
        if len(self._cache) >= self.max_entries:
            evicted = self._order.pop(0)
            self._cache.pop(evicted, None)
        self._cache[key] = copy.deepcopy(out)
        self._order.append(key)
        return out

    # 其余方法直接委托（缓存只针对形状化主成本；真实路径由调用点接线驱动）
    def merge_nodes(self, node_infos):
        return self.inner.merge_nodes(node_infos)

    def rebalance_suggest(self, fragment_info):
        return self.inner.rebalance_suggest(fragment_info)

    def score_keys(self, tokens):
        return self.inner.score_keys(tokens)
