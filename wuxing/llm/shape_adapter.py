"""默认模型的形状化适配（2026-09-19 用户裁决）。

真实形状化使用**用户配置的默认模型**（`cfg.llm`）——非域级路由、非供应商专用
（此前硬编码 DeepSeek）。做法：把引擎 provider（工厂统一构造，任意供应商类型）
适配进 golden_ratio 的 LLMClient 协议——基类 DeepSeekLLM 的四个方法
（shape_task/merge_nodes/rebalance_suggest/score_keys）只依赖 `_chat` 的 JSON 契约，
本适配仅覆写 `_chat` 委托 `provider.chat`。

真测修复（2026-09-25 · REAL-1）：引擎 provider（无 tools 路径）直接返回 **str**——
此前只认 `.text`/dict → 取词为空 → `json.loads("")` 失败 → 真实形状化必然降级 mock。
现接受 str / 对象 `.text` / dict `content|text`，并容错 ```json 围栏与前后说明文字。
"""
import json
import re

from golden_ratio.realllm import DeepSeekLLM

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _response_text(resp) -> str:
    """provider 返回形态 → 文本（str / 对象 .text / dict content|text）。"""
    if isinstance(resp, str):
        return resp
    text = getattr(resp, "text", None)
    if text is None and isinstance(resp, dict):
        text = resp.get("content") or resp.get("text") or ""
    return str(text or "")


def _json_payload(text: str) -> str:
    """抽取 JSON 载荷：剥 ``` 围栏；有前后说明文字时取首尾括号段。"""
    s = str(text or "").strip()
    m = _FENCE_RE.search(s)
    if m:
        return m.group(1).strip()
    if s and not s.startswith(("{", "[")):
        start = next((i for i, ch in enumerate(s) if ch in "{["), -1)
        if start >= 0:
            end = max(s.rfind("}"), s.rfind("]"))
            if end > start:
                return s[start:end + 1]
    return s


class DefaultModelShapeLlm(DeepSeekLLM):
    """引擎默认 provider → golden_ratio 形状化客户端（4 方法沿用基类）。"""

    def __init__(self, provider, model_name: str = "default"):
        super().__init__(model=str(model_name or "default"),
                         api_key="engine-provider")
        self._provider = provider

    def _chat(self, messages, json_mode=True, temperature=0.0):
        """委托引擎 provider；输出契约与基类一致（解析后的 JSON）。

        注：json_mode/temperature 不当前透传（provider.chat 无对应参数）——
        基类 `_chat_with_retry` 的重试多样性在适配层不生效（已知限制）。
        """
        resp = self._provider.chat(messages)
        return json.loads(_json_payload(_response_text(resp)))
