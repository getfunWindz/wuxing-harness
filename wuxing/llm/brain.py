"""智脑记忆（P14 Q2-B：案例式 + 词元 Jaccard——确定性，无嵌入）。

- record：同 key+domain+model 合并（attempts+1，success=最新）
- search：词元 Jaccard 相似度 top-K（golden_ratio rebalance 先例）
- LRU：容量上限（最后写入者保留）
- 持久化：工作区 brain_memory.json
"""
import contextlib
import json
import os
import pathlib
import threading
import time

from wuxing.filelock import lock_for


def _tokens(key: str) -> set:
    """词元化：jieba 分词（2026-09-06 修复——旧 split 对中文长串零命中，
    智脑收益未证明的根因之一——与 R3 缓存同款分词）；纯符号 token 过滤。"""
    import jieba
    return {p.strip() for p in jieba.lcut(key.replace("|", " "))
            if p.strip() and any(ch.isalnum() for ch in p)}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a | b) else 0.0


def case_success_rate(case: dict) -> float:
    """B1（审查）：案例成功率 = success_count / attempts（规格「成功率≥0.8」口径）。

    旧数据兼容：无 success_count（历史记录）→ 回退 latest 布尔（1 样本估计）。
    """
    attempts = int(case.get("attempts", 0) or 0)
    if attempts <= 0:
        return 0.0
    if "success_count" in case:
        return round(int(case.get("success_count", 0)) / attempts, 4)
    return 1.0 if case.get("success") else 0.0


def _decay(case: dict, now: float | None = None) -> float:
    """L3-2 遗忘衰减（降权不删除——7 步第 6 步，与缓存/成本联动）。

    - 时间：30 天半衰期（0.5 ** (days/30)）——过期经验随使用间隔降权
    - 尝试：每多一次尝试 0.7 倍（反复失败/反复命中的经验权重递减）
    - 不删除：仅参与排序打分；用例由三级池 LRU 逐出（唯一删除路径）
    """
    now = now or time.time()
    days = max(0.0, (now - (case.get("last_at") or now)) / 86400.0)
    t = 0.5 ** (days / 30.0)
    a = 0.7 ** max(0, int(case.get("attempts", 1)) - 1)
    return round(t * a, 6)


def search_scored(cases: list, fragment_key: str, top_k: int = 5,
                  order: str = "tier"):
    """检索+评分（默认 tier 优先——三级参照表语义不改；同级 sim × decay）。

    order="similarity"（第七轮审查）：强证据判定需要「最相似优先」序——
    tier-first 下弱相似 high 案例会排在精确匹配之前，使判定取错样本。
    """
    q = _tokens(fragment_key)
    scored = []
    for c in cases:
        s = jaccard(q, _tokens(c["key"]))
        if s > 0:
            scored.append({**c, "similarity": s,
                           "score": round(s * _decay(c), 6)})
    if order == "similarity":
        scored.sort(key=lambda x: (-x["similarity"],
                                   _TIER_RANK.get(x.get("tier", "normal"), 1),
                                   x["key"]))
    else:
        scored.sort(key=lambda x: (_TIER_RANK.get(x.get("tier", "normal"), 1),
                                   -x["score"], x["key"]))
    return scored[:top_k]


def classify_tier(success: bool, share: float | None) -> str:
    """智脑三级分级（用户裁决 2026-09-06——等级参照表）。

    high：成功且碎片粒度占比 ∈ [0.382, 0.618]（黄金比区间——知识库评估口径纪律）
    low：完成度差（失败）；其余成功 → normal。
    share=None（粒度数据缺失）时：成功→normal（谨慎——不越级升 high）。
    """
    if not success:
        return "low"
    if share is None:
        return "normal"
    if 0.382 <= share <= 0.618:
        return "high"
    return "normal"


_TIER_RANK = {"high": 0, "normal": 1, "low": 2}


class BrainMemory:
    def __init__(self, path: pathlib.Path, max_cases: int = 500,
                 high_cases: int = 191, low_cases: int = 191):
        """三级参照表（黄金比容量：high/low = 191 ≈ 0.382×500——用户建议）。"""
        self.path = pathlib.Path(path)
        self.max_cases = max_cases
        self.high_cases = high_cases
        self.low_cases = low_cases
        self.cases = []  # [{key, domain, model, success, attempts, last_at, tier}]
        # B3（审查）：并发 record 竞态——check-then-act 窗口（P16 并行碎片共写）
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with lock_for(self.path):
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                self.cases = raw.get("cases", [])
            except Exception:
                self.cases = []

    def _save(self):
        """B3（技术债收口 2026-09-12）：原子写（tmp + os.replace）——
        崩半写不得破坏既有记忆（与 manifest/artifact 同源惯例）。"""
        tmp = None
        try:
            with lock_for(self.path):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(self.path.suffix + ".tmp")
                tmp.write_text(
                    json.dumps({"cases": self.cases}, ensure_ascii=False,
                               indent=2),
                    encoding="utf-8")
                os.replace(tmp, self.path)
        except OSError:
            if tmp is not None:
                with contextlib.suppress(OSError):
                    tmp.unlink(missing_ok=True)

    def search(self, fragment_key: str, top_k: int = 5,
               domain: str | None = None, order: str = "tier") -> list:
        """检索相似案例（Jaccard > 0；默认等级优先——high > normal > low，
        同级按 相似度×遗忘衰减 排序——L3-2 降权不删除）。

        domain（第七轮审查）：域过滤**先于** top-k 截断——否则他域案例可
        挤掉同域精确匹配（记忆指导整体失效）。order="similarity" 供强证据
        判定（最相似优先——tier-first 会把弱相似 high 排在精确匹配之前）。
        """
        cases = self.cases
        if domain is not None:
            cases = [c for c in cases if c.get("domain") == domain]
        return search_scored(cases, fragment_key, top_k, order)

    def record(self, key, domain, model, success, spec=None, tier="normal"):
        """记录案例（分级列队——high/low 容量上限 LRU 逐出，谨慎入库由调用方分级）。

        全程持锁：合并/追加/容量/持久化原子——并发碎片不丢合并（B3）。
        """
        with self._lock:
            for c in self.cases:
                if c["key"] == key and c["domain"] == domain and c["model"] == model:
                    c["attempts"] += 1
                    # B1：success_count 精确累加（成功率口径——仅 latest 布尔不可用）
                    c["success_count"] = int(c.get("success_count", 0)) + \
                        (1 if success else 0)
                    c["success"] = success
                    c["last_at"] = time.time()
                    c["tier"] = tier
                    self._save()
                    return
            self.cases.append({"key": key, "domain": domain, "model": model,
                               "spec": spec or model, "success": success,
                               "success_count": 1 if success else 0,
                               "attempts": 1, "last_at": time.time(), "tier": tier})
            # 三级池容量（LRU 按池逐出——高/低参照谨慎保留）
            self._enforce_capacity()
            self._save()

    def _enforce_capacity(self):
        """按 tier 上限逐出最旧（high/low 池容量 191——黄金比；normal 500）。"""
        for tier, cap in (("high", self.high_cases), ("low", self.low_cases),
                          ("normal", self.max_cases)):
            pool = [c for c in self.cases if c.get("tier") == tier]
            if len(pool) > cap:
                pool.sort(key=lambda x: x["last_at"])
                evict = {id(c) for c in pool[:len(pool) - cap]}
                self.cases = [c for c in self.cases if id(c) not in evict]
