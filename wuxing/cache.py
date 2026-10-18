"""缓存层（P9：R1 精确键值 + R2 形状化持久）。

ReplyCache：JSON 落盘键值缓存（FIFO 容量/损坏容错/深拷贝隔离/命中统计）
ShapeCache：形状化特化（key = task_text 规范化——跨会话同任务）
"""
import copy
import json
import logging
import pathlib
import threading

import jieba

from wuxing.filelock import lock_for


def _tokens_for_sim(text: str) -> set:
    """语义检索词元（jieba——中文短文本微漂移可命中；整串 split 对中文退化为 0）。

    D3（2026-09-07）：lru 缓存——域级键固定（每 run_unit 一次检索——多碎片
    重复分词；缓存保确定性——同输入同结果）。
    """
    return _tokens_cached(text)


from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=256)
def _tokens_cached(text: str) -> frozenset:
    return frozenset(w.strip() for w in jieba.lcut(text) if w.strip())


def _serialize(v):
    """缓存值序列化协议（P0 T5）：ToolCallResult（含工具调用）↔ JSON 可往返。

    旧缺陷：对象直接 json.dumps → TypeError 被 _save 的 except 吞掉 →
    缓存永不落盘（跨引擎恢复基准归零）。
    """
    if isinstance(v, dict):
        return {k: _serialize(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_serialize(x) for x in v]
    if hasattr(v, "tool_calls") and hasattr(v, "text"):  # ToolCallResult（鸭子）
        return {"__tcr__": True, "text": v.text, "tool_calls": v.tool_calls}
    return v


def _deserialize(v):
    if isinstance(v, dict):
        if v.get("__tcr__"):
            from wuxing.llm.tool_results import ToolCallResult
            return ToolCallResult(text=v.get("text", ""),
                                  tool_calls=v.get("tool_calls", []) or [])
        return {k: _deserialize(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_deserialize(x) for x in v]
    return v


class ReplyCache:
    def __init__(self, path: pathlib.Path, max_entries: int = 500,
                 similar_threshold: float = 0.75):
        self.path = pathlib.Path(path)
        self.max_entries = max_entries
        # P1 T3（债 4）：R3 语义检索——相似阈值（0=关闭；默认 0.75：命中标点/空白
        # 微漂移 J≈0.8，不误判真变体 J≤0.57——实测边界）
        self.similar_threshold = similar_threshold
        self.hits = 0
        self.misses = 0
        self.similar_hits = 0  # 语义命中统计（区别于精确 hits）
        self._data = {}     # key -> value
        self._order = []    # FIFO 顺序
        self._sim_index = {}  # key -> tokens（put 建/evict 删——查询热路径不分词）
        self._lock = threading.Lock()  # P16：多手并行缓存读写互斥
        self._load()

    def _load(self):
        """加载磁盘缓存；损坏/缺失 → 重建空缓存（韧性：不崩溃）。"""
        if not self.path.exists():
            return
        try:
            with lock_for(self.path):
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = raw.get("entries", {})
            self._order = raw.get("order", [])
            self._rebuild_sim_index()
        except Exception:
            self._data = {}
            self._order = []
            self._sim_index = {}

    def _rebuild_sim_index(self):
        """加载后重建词元索引（持久化只存 values——索引为衍生数据）。"""
        self._sim_index = {k: _tokens_for_sim(k) for k in self._data}

    def _save(self):
        try:
            with lock_for(self.path):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(
                    json.dumps({"entries": self._data, "order": self._order},
                               ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("缓存写盘失败（不阻断）：%s", exc)

    def get(self, key: str):
        with self._lock:  # P16：并发命中统计/读取互斥
            if key in self._data:
                self.hits += 1
                return _deserialize(copy.deepcopy(self._data[key]))  # 深拷贝：防污染
            self.misses += 1
            return None

    def put(self, key: str, value):
        with self._lock:  # P16 并发写入互斥（L2-2 修订：evict/索引维护全部入临界区——
            # 旧实现 evict 在锁外 → 并发 similar_get 迭代时字典变更 RuntimeError）
            if key not in self._data:
                if len(self._order) >= self.max_entries:
                    evicted = self._order.pop(0)
                    self._data.pop(evicted, None)
                    self._sim_index.pop(evicted, None)
                self._order.append(key)
            self._data[key] = _serialize(copy.deepcopy(value))
            self._sim_index[key] = _tokens_for_sim(key)  # P1 T3：索引随写入维护
            self._save()

    def clear(self):
        """（保留 API——P13 记录：当前无生产调用，缓存管理备用）。"""
        with self._lock:
            self._data = {}
            self._order = []
            self._sim_index = {}

    @staticmethod
    def _difference_trivial(a: str, b: str, max_mid: int = 4) -> bool:
        """差异段是否可忽略：去标点/空白后相同（纯漂移），或实义差异极短（≤max_mid）。

        A 级修复（2026-09-12 精确测试 v2 暴露）：共享大前缀 + 一行目标差异的
        跨单元提示 Jaccard 极高，但差异段含**实质指令**——不得复用（防兄弟单元
        响应串扰）；保留「标点/空白微漂移」原语义（债 4/H1 目标）。
        """
        sa = "".join(ch for ch in a if ch.isalnum())
        sb = "".join(ch for ch in b if ch.isalnum())
        if sa == sb:
            return True  # 差异仅标点/空白（含多点扩散）
        n = min(len(sa), len(sb))
        i = 0
        while i < n and sa[i] == sb[i]:
            i += 1
        j = 0
        while j < n - i and sa[-1 - j] == sb[-1 - j]:
            j += 1
        return (len(sa) - i - j) + (len(sb) - i - j) <= max_mid

    def similar_get(self, key: str):
        """P1 T3（债 4）：语义检索——精确 miss 后按 jieba Jaccard 找最相似键。

        返回 (value, similarity)；阈值内不命中或阈值=0（关闭）→ (None, 0.0)。
        安全语义：相似度 >= 阈值才复用（微漂移），真变体不误判。
        H1（2026-09-07 缓存层加固）：**域隔离**——键格式 `{domain_id}|{prompt}`；
        仅同域键参与相似检索（跨域复用=污染：工具集/契约/验收语义不同——
        即使 Jaccard 高也不得复用）。无域前缀的键（非单元键）不隔离。
        """
        if self.similar_threshold <= 0:
            return None, 0.0
        domain_prefix = key.split("|", 1)[0] + "|" if "|" in key else None
        with self._lock:
            q_tokens = _tokens_for_sim(key)  # 仅查询键分词一次（新键无索引）
            if not q_tokens:
                return None, 0.0
            best_key, best_sim = None, 0.0
            for k, v_tokens in self._sim_index.items():
                if k == key:
                    continue  # 精确命中归属 get()
                if domain_prefix is not None and not k.startswith(domain_prefix):
                    continue  # H1：域隔离（跨域不参选）
                s = len(q_tokens & v_tokens) / len(q_tokens | v_tokens)
                if s > best_sim:
                    best_key = k
                    best_sim = s
            if best_key is not None and best_sim >= self.similar_threshold:
                # A 级修复（2026-09-12）：实质差异守卫——差异段含实义字符
                # 且超过容错长度（跨单元/不同目标）→ 拒绝复用
                if not self._difference_trivial(key, best_key):
                    return None, 0.0
                self.similar_hits += 1
                return _deserialize(copy.deepcopy(self._data[best_key])), best_sim
            return None, 0.0

    def __len__(self):
        """（保留 API——P13 记录：当前无生产调用）。"""
        return len(self._data)


class ShapeCache(ReplyCache):
    """形状化特化（key = task_text 规范化——空白归一 + 英文小写）。"""
    def key_for(self, task_text: str) -> str:
        return " ".join(str(task_text).split()).lower()

    def put(self, task_text: str, dag: dict):
        return super().put(self.key_for(task_text), copy.deepcopy(dag))

    def get(self, task_text: str):
        return super().get(self.key_for(task_text))

    def similar_get(self, task_text: str):
        """B11（审查）：查询侧与写入侧同口径——similar_get 必须经 key_for 规范化。

        规范化后精确命中（== 存储键）直接返回（写入侧同口径——调用方 raw get
        已 miss 才走到这里：语义命中计入 similar_hits）；否则走基类相似兜底。
        注意：基类 k==key 跳过逻辑不适用于规范化精确命中（那是 get 的职责——
        但本层调用方以原始键 get，规范化键相等即语义命中）。
        """
        key = self.key_for(task_text)
        with self._lock:
            if key in self._data:
                self.similar_hits += 1
                return _deserialize(copy.deepcopy(self._data[key])), 1.0
        return super().similar_get(key)
