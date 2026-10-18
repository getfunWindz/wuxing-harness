"""ModelRouter（P4.5：域级模型路由——多智能体协作-多模型协作的机械实现）。

配置形态（EngineConfig.router 或构造参数）：
  {"plan": "deepseek:deepseek-chat",
   "verify": "anthropic:claude-sonnet-4-5",
   "_default": "mock"}          # 未列出域走 _default（缺省 mock）
  # P15 决策 A：域值也可以是候选列表（多 API 真实场景）——
  #   "verify": ["deepseek:deepseek-chat", "anthropic:claude-sonnet-5"]
  #   无记忆回退 = 候选[0]；智脑从候选集内按证据选择

P14 智脑（Q3-C 证据分级）：for_domain(domain_id, fragment_key=None, brain=None)
  - 强证据（相似≥0.7 且成功率≥0.8）→ 确定性覆盖记忆模型
  - 弱证据 → 轮盘加权（成功率×相似度）
  - 无证据/无 brain → 回退域路由（现状）
"""
import json
import logging
import random

from wuxing.llm.factory import create_provider

logger = logging.getLogger(__name__)

STRONG_SIM = 0.7
STRONG_RATE = 0.8
EXPLORE_PRIOR = 0.25  # 探索先验权重（P15：候选未被使用 → 先验成功率 0.5 × 弱相似 0.5）


def strong_evidence(case: dict) -> bool:
    """B1（审查）：强证据判定——规格「相似≥0.7 且 成功率≥0.8」。

    此前误用 latest 布尔（best["success"]）：最新成功但历史 2/3 也当强证据；
    1 次成功也当成功率 100%——机制裁决口径失准。
    """
    from wuxing.llm.brain import case_success_rate
    return (case.get("similarity", 0.0) >= STRONG_SIM
            and case_success_rate(case) >= STRONG_RATE)


def _wheel(hits: list, candidates: list):
    """轮盘构造：记忆案例（成功率×相似度）+ 未探索候选（探索先验——否则智脑死锁首个模型）。

    P15 发现：纯利用轮盘只含「用过的模型」→ 在线学习永远不尝试未用候选 → A/B 结构性零信号。
    """
    weights, picked = [], []
    from wuxing.llm.brain import case_success_rate
    for h in hits[:3]:
        w = case_success_rate(h) * h["similarity"]
        weights.append(w)
        picked.append(h.get("spec") or h["model"])
    for cand in candidates:
        if cand not in picked:
            weights.append(EXPLORE_PRIOR)
            picked.append(cand)
    return weights, picked


class ModelRouter:
    def __init__(self, spec: dict, brain=None, max_retries: int | None = None,
                 timeout: float | None = None, cache_key: str = "",
                 providers: dict | None = None):
        self._spec = dict(spec or {})
        self._cache = {}
        self._brain = brain  # P14 智脑（可选）
        self._max_retries = max_retries  # 配置补遗：retry/timeout 传导
        self._timeout = timeout
        self._cache_key = cache_key  # Pi 同款：会话亲和键（透传 provider）
        self._providers = dict(providers or {})  # R5-1：provider/model 引用解析表

    def _resolve_candidates(self, domain_id: str) -> list:
        """域候选集（P15 决策 A）：dict spec 为单候选——不可 list() 拆 keys。"""
        spec = self._spec.get(domain_id) or self._spec.get("_default") or "mock"
        if isinstance(spec, (str, dict)):
            return [spec]
        return list(spec)

    def candidate_count(self, domain_id: str) -> int:
        """S1-A/L2：域候选数（确定性路径降级链上界）。"""
        return max(1, len(self._resolve_candidates(domain_id)))

    def for_domain(self, domain_id: str, fragment_key: str | None = None,
                   candidate_index: int = 0):
        if fragment_key and self._brain is not None:
            picked = self._brain_pick(domain_id, fragment_key)
            if picked is not None:
                # L3-4：选择来源标记（评测归因——记忆引导 vs 回退可量化）
                picked._picked_by_brain = True
                return picked
        # 回退域路由（现状）：候选[0]——无记忆/无证据时行为可预期；
        # S1-A/L2：candidate_index 由自动恢复环消费（降级链序）
        candidates = self._resolve_candidates(domain_id)
        idx = max(0, min(int(candidate_index), len(candidates) - 1))
        # 缓存键：dict spec（中转站 base_url）不可哈希 → 序列化键；含候选序
        cache_key = (domain_id, idx, tuple(
            json.dumps(c, sort_keys=True, ensure_ascii=False) if isinstance(c, dict) else c
            for c in candidates))
        if cache_key in self._cache:
            return self._cache[cache_key]
        provider = create_provider(candidates[idx], max_retries=self._max_retries,
                                   timeout=self._timeout,
                                   providers=self._providers)
        provider._picked_by_brain = False
        if self._cache_key:
            try:
                provider._cache_key = self._cache_key
            except Exception as exc:
                logger.debug("provider 缓存键注入失败（不阻断）：%s", exc)
        self._cache[cache_key] = provider
        return provider

    def _brain_pick(self, domain_id: str, fragment_key: str):
        """智脑三级决策；返回 provider 或 None（无证据回退）。

        D1c 修复：记忆案例的 model 字段为旧 name()（openai-compat: 等不可回构）——
        优先用 spec 字段（create_provider 可回构）；无 spec 时回退 model（兼容旧数据）。
        第七轮审查修复：强证据判定在「同域 + 相似度序」命中集内做——tier-first
        的 hits[0] 可能是弱相似 high（压制精确匹配），且域过滤须先于 top-k 截断。
        """
        hits = self._brain.search(fragment_key, domain=domain_id)
        if not hits:
            return None
        # 强证据（规格 §15.3：相似≥0.7 且 成功率≥0.8）→ 确定性覆盖：
        # 取最相似的强证据命中（不依赖 tier 首位——三级参照表语义不动）
        by_sim = self._brain.search(fragment_key, domain=domain_id,
                                    order="similarity")
        strong = [h for h in by_sim if strong_evidence(h)]
        if strong:
            chosen = strong[0]
            try:
                provider = create_provider(chosen.get("spec") or chosen["model"],
                                           max_retries=self._max_retries,
                                           timeout=self._timeout,
                                           providers=self._providers)
            except (ValueError, RuntimeError):
                # 2026-10-01 P1：历史记忆可能含不可回构 spec（旧 responses name()）
                # 或缺凭据的 spec（RuntimeError『未配置 …_API_KEY』）——
                # 一律安全回退域路由，不得中断任务（修复后新记录不再产生）。
                logger.warning("智脑记忆 spec 回构失败，回退域路由：%r",
                               chosen.get("spec") or chosen.get("model"))
                return None
            self._apply_cache_key(provider)
            return provider
        # 弱证据：轮盘加权（成功率×相似度 + 未探索候选先验——seed 确定性测试用）
        weights, candidates = _wheel(hits, self._resolve_candidates(domain_id))
        if not weights or sum(weights) <= 0:
            return None  # 全零权重 → 回退
        chosen = random.choices(candidates, weights=weights, k=1)[0]
        try:
            provider = create_provider(chosen, max_retries=self._max_retries,
                                       timeout=self._timeout,
                                       providers=self._providers)
        except (ValueError, RuntimeError):
            # 2026-10-01 P1：轮盘候选可能含记忆中的不可回构/缺凭据 spec
            # （历史脏数据）——安全回退域路由，不得中断任务。
            logger.warning("智脑轮盘选中不可回构 spec，回退域路由：%r", chosen)
            return None
        self._apply_cache_key(provider)
        return provider

    def _apply_cache_key(self, provider):
        """Pi 同款：会话亲和键透传（鸭子类型——假 provider 无害）。"""
        if self._cache_key:
            try:
                provider._cache_key = self._cache_key
            except Exception as exc:
                logger.debug("provider 缓存键注入失败（不阻断）：%s", exc)

    def default(self):
        return self.for_domain("_default")
