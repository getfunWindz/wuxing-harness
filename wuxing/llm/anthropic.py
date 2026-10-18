"""Anthropic Provider（P4.5：Messages API——system 分离 + anthropic-version header）。"""
import json
import os

import requests

from wuxing.llm.base import BaseLlmProvider


class AnthropicProvider(BaseLlmProvider):
    def __init__(self, model="claude-sonnet-4-5", base_url="https://api.anthropic.com/v1",
                 api_key=None, timeout=60.0, max_retries=2, _http=None, headers=None):
        super().__init__(max_retries=max_retries)
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.timeout = timeout
        self._http = _http or requests
        self._headers = dict(headers or {})  # 中转站网关自定义头（claude-cli UA 等）

    def name(self): return f"anthropic:{self.model}"

    def spec(self):
        ref = getattr(self, "_credential_ref", None)
        if self.base_url != "https://api.anthropic.com/v1" or self._headers or ref:
            return {"type": "anthropic", "model": self.model, "base_url": self.base_url,
                    **({"headers": dict(self._headers)} if self._headers else {}),
                    **({"credential_ref": str(ref)} if ref else {})}
        return f"anthropic:{self.model}"

    def cache_capabilities(self) -> dict:
        """P10 E4：Anthropic Messages API 支持 cache_control 标记（系统/工具段）。"""
        return {"server_prompt_cache": "anthropic"}

    @staticmethod
    def _to_anthropic_tools(tools: list) -> list:
        """L0-2（审查 A2）：OpenAI 兼容 schema → Anthropic 格式。

        OpenAI: {type: "function", function: {name, description, parameters}}
        Anthropic: {name, description, input_schema}（无 type/function 包装——
        此前 tools 参数被丢弃，Claude 通道只能走脆弱文本协议 TOOLCALL 行）。
        Pi 同款（2026-09-10 用户裁决）：**最后一项打 cache_control**——
        工具定义整段进服务端缓存（system 断点之外的工具段断点）。
        """
        out = []
        for t in tools or []:
            fn = t.get("function", t) if isinstance(t, dict) else {}
            out.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", "") or "",
                "input_schema": fn.get("parameters", fn.get("input_schema",
                                                              {"type": "object"})),
            })
        if out:
            out[-1]["cache_control"] = {"type": "ephemeral"}
        return out

    @staticmethod
    def _parse_content(blocks: list):
        """L0-2：content blocks → str 或 ToolCallResult（text + tool_use）。

        有 tool_use → ToolCallResult（原生工具调用结构化——runner 直接执行）；
        纯文本 → str（保持既有消费路径）。
        """
        texts, calls = [], []
        for c in blocks or []:
            if c.get("type") == "text":
                texts.append(c.get("text", ""))
            elif c.get("type") == "tool_use":
                calls.append({"name": c.get("name", ""),
                              "arguments": c.get("input", {}) or {}})
        text = "".join(texts)
        if calls:
            from wuxing.llm.tool_results import ToolCallResult
            return ToolCallResult(text=text, tool_calls=calls)
        return text

    def build_messages_prefix(self, system_parts: list, tools: list | None = None) -> dict:
        """P10 E1：构建带缓存标记的请求载荷（Anthropic 格式）。

        稳定前缀（system/工具定义）打 cache_control（ephemeral）——仅当能力支持。
        """
        caps = self.cache_capabilities()
        system_text = "\n".join(system_parts)
        if caps["server_prompt_cache"] == "anthropic":
            return {"system": [{"type": "text", "text": system_text,
                                "cache_control": {"type": "ephemeral"}}]}
        return {"system": system_text}

    def chat(self, messages, tools: list | None = None):
        if not self.api_key and self._http is requests:
            raise RuntimeError("未配置 ANTHROPIC_API_KEY")
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        user_msgs = [m for m in messages if m.get("role") != "system"]
        payload = {"model": self.model, "messages": user_msgs, "max_tokens": 4096}
        # L0-2（审查 A2）：原生 tools 接线——Anthropic 格式（此前被忽略）
        if tools:
            payload["tools"] = self._to_anthropic_tools(tools)
        if system_parts:
            # P1 T2（债 3 接线）：system 段打 cache_control（block 数组）——
            # 稳定前缀命中服务端缓存的唯一路径
            payload["system"] = self.build_messages_prefix(system_parts, tools)["system"]
        return self._retry_with_backoff(lambda: self._chat_once(payload))

    def _chat_once(self, payload):
        resp = self._http.post(
            f"{self.base_url}/messages",
            headers={"x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json", **self._headers},
            json=payload, timeout=self.timeout)
        resp.raise_for_status()
        try:
            data = resp.json()
        except (ValueError, json.JSONDecodeError) as exc:
            # 韧性：200 非 JSON（中转站错误页）——友好报错不裸崩
            raise RuntimeError(
                f"provider 返回非 JSON（status={getattr(resp, 'status_code', '?')}）: "
                f"{getattr(resp, 'text', '')[:120]}") from exc
        # P1 T1：usage 真值解析（债 1）——cache_read_input_tokens / cache_creation_input_tokens
        # B 级修复（2026-09-11 审查）：Anthropic input_tokens 不含 cache 读写——
        # usage.input 统一为「总输入」（input+creation+read，与 DeepSeek
        # prompt_tokens 口径一致：命中率 = cache_read/input ≤1；成本估算不出现负值）
        u = data.get("usage") or {}
        _inp = int(u.get("input_tokens", 0) or 0)
        _cr = int(u.get("cache_read_input_tokens", 0) or 0)
        _cw = int(u.get("cache_creation_input_tokens", 0) or 0)
        self._record_usage({"input": _inp + _cr + _cw,
                            "output": u.get("output_tokens", 0),
                            "cache_read": _cr, "cache_write": _cw})
        # L0-2：tool_use 块 → ToolCallResult（原生工具调用——runner 结构化执行）
        return self._parse_content(data.get("content", []))
