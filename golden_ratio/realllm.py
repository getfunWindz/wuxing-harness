"""DeepSeek RealLLM（B 终态客户端：OpenAI 兼容 chat/completions + JSON 模式）。

Q6 决策落地：LLMClient 只换实现不换签名。接入方式（用户 harness 启用）：
    from golden_ratio.realllm import DeepSeekLLM
    from golden_ratio.cache import CachedLLM
    from golden_ratio.guard import BudgetGuard, BudgetExceeded
    llm = CachedLLM(BudgetGuard(DeepSeekLLM(), max_calls=3))   # 缓存命中不耗预算
    cfg.llm_merge_enabled = cfg.llm_rebalance_enabled = cfg.llm_key_scoring_enabled = True

成本护栏（LLM接入降成本方案）：结构校验（shape.py 已接入，合法即信任单次输出）、
输出缓存（CachedLLM，任务文本归一化命中）、预算护栏（BudgetGuard，超限 BudgetExceeded）。

API key：环境变量 DEEPSEEK_API_KEY（默认），或构造参数 api_key。
"""
import json
import os

import requests

from golden_ratio.llm import LLMClient

SHAPE_SYSTEM_PROMPT = (
    "你是任务分解引擎。把用户任务分解为任务 DAG，只输出严格 JSON（无 Markdown、无解释）。\n"
    "格式: {\"nodes\": [{\"id\": \"n1\", \"text\": \"流程名\", "
    "\"domain_dist\": {\"领域\": 置信度}, \"trades\": [\"工种\"], "
    "\"complexity\": \"low|mid|high\", \"deliverable\": \"text|code|data|decision\", "
    "\"color_weight\": 0~1}, ...], \"edges\": [[上游id, 下游id], ...]}\n"
    "硬性约束: \n"
    "1. 节点 id 必须是字符串（\"n1\", \"n2\"…），edges 端点必须引用这些 id 字符串（禁止数字 1/2）；\n"
    "2. DAG 必须连通：除入度0的根节点外，每个节点必须有至少一条上游边（禁止孤立节点）；\n"
    "3. 无环、节点 id 唯一、领域置信度为正数；\n"
    "4. 重要度 color_weight ∈ (0,1]，越大越重要。"
    "5. 若任务包含实现/编写/构建/开发等动作，DAG 必须包含至少一个执行节点"
    "   （deliverable 为 code 或 text）——不得只输出规划与验证节点"
    "   （S-B 修正 2026-09-05：冒烟实证真 LLM 偶发遗漏执行节点 → 契约加固）。\n"
    "6. 节点单一职责（真测 REAL-3）：构造与验收不得混在同一节点——"
    "   构造节点只描述要产出的产品（创建/编写/实现/生成；测试与样例资产归此类，"
    "   deliverable=code/data），验收节点只描述核对与结论（验收/校验/确认）。"
    "   禁止把「运行/确认/验收」动作与「创建/编写」产物写进同一节点文本。"
)


class DeepSeekLLM(LLMClient):
    def __init__(self, model="deepseek-chat", base_url="https://api.deepseek.com",
                 api_key=None, timeout=60.0, max_retries=2):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("未配置 DeepSeek API key（环境变量 DEEPSEEK_API_KEY 或参数 api_key）")
        self.timeout = timeout
        self.max_retries = max_retries
        self.call_count = 0

    def _chat(self, messages, json_mode=True, temperature=0.0):
        """协议层：POST /chat/completions，返回解析后的 JSON。

        子类/测试可覆盖此方法（不触网路径）。temperature 由重试序列控制（0→0.3→0.6）。
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,     # 首次 0；重试递增（纠错需要多样性）
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    def _chat_with_retry(self, messages, json_mode=True):
        """重试：网络/HTTP 异常重试 max_retries 次；JSON 解析失败重试一次；
        每次重试 temperature 递增（0→0.3→0.6）——纠错重试需要输出多样性
        （temperature=0 时重试输出雷同，重试机制无效——真接入实测发现）。"""
        last_exc = None
        temp_seq = [0.0, 0.3, 0.6, 0.9]
        for attempt in range(self.max_retries + 1):
            self.call_count += 1
            try:
                return self._chat(messages, json_mode=json_mode,
                                  temperature=temp_seq[min(attempt, len(temp_seq) - 1)])
            except (requests.RequestException, OSError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    continue
                raise
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                last_exc = exc
                if attempt == 0:
                    continue                    # JSON 解析失败重试一次
                raise ValueError(f"DeepSeek 输出无法解析为 JSON: {exc}") from exc
        raise last_exc

    # ---- LLMClient 契约实现 ----

    def shape_task(self, task_text):
        messages = [
            {"role": "system", "content": SHAPE_SYSTEM_PROMPT},
            {"role": "user", "content": task_text},
        ]
        raw = self._chat_with_retry(messages)
        if not isinstance(raw, dict):
            # LLM 输出契约违例（JSON 解析成功但形状不符）——保留 ValueError（非参数类型错误）
            raise ValueError("shape_task 输出必须是 JSON 对象")  # noqa: TRY004
        return raw

    def merge_nodes(self, node_infos):
        prompt = ("把以下节点合并为工作包（WBS）：每包工时 8-80 小时（尽量接近 40h），"
                  "同一交付物/同一执行者可合并；输出 [[节点id,...],...]，务必覆盖全部节点且不重复。\n"
                  + json.dumps(node_infos, ensure_ascii=False))
        raw = self._chat_with_retry([
            {"role": "system", "content": "只输出分组 JSON 数组（无解释）。"},
            {"role": "user", "content": prompt},
        ])
        if not isinstance(raw, list):
            # LLM 输出契约违例（JSON 解析成功但形状不符）——保留 ValueError（非参数类型错误）
            raise ValueError("merge_nodes 输出必须是 JSON 数组")  # noqa: TRY004
        return raw

    def rebalance_suggest(self, fragment_info):
        prompt = ("给定碎片集合，给出黄金比再平衡的迁移建议（过胖碎片迁出低价值节点、"
                  "过小碎片并入最近碎片）。只输出 {\"moves\": [{\"from\", \"to\", \"node_ids\"}]}。\n"
                  + json.dumps(fragment_info, ensure_ascii=False))
        raw = self._chat_with_retry([
            {"role": "system", "content": "只输出 moves JSON 对象，无可迁移时 {\"moves\": []}。"},
            {"role": "user", "content": prompt},
        ])
        if not isinstance(raw, dict):
            # LLM 输出契约违例（JSON 解析成功但形状不符）——保留 ValueError（非参数类型错误）
            raise ValueError("rebalance_suggest 输出必须是 JSON 对象")  # noqa: TRY004
        return raw

    def score_keys(self, tokens):
        prompt = "为以下 key 候选打分（0~1，按对任务分配的重要度）：\n" + json.dumps(tokens, ensure_ascii=False)
        raw = self._chat_with_retry([
            {"role": "system", "content": "只输出 {\"词\": 分数} JSON 对象。"},
            {"role": "user", "content": prompt},
        ])
        if not isinstance(raw, dict):
            # LLM 输出契约违例（JSON 解析成功但形状不符）——保留 ValueError（非参数类型错误）
            raise ValueError("score_keys 输出必须是 JSON 对象")  # noqa: TRY004
        return raw
