"""DeepSeek（P4.5 起 = OpenAIChatProvider 的默认配置实例，保留向后兼容）。"""
import os

from wuxing.llm.openai import OpenAIChatProvider


class DeepSeekLlmProvider(OpenAIChatProvider):
    def __init__(self, model="deepseek-chat", base_url="https://api.deepseek.com",
                 api_key=None, timeout=60.0, max_retries=2, _http=None, headers=None,
                 temperature=0.0):
        if api_key is None:
            # 预检发现（P15 真跑）：OpenAIChatProvider 的 key 顺序是
            # OPENAI_API_KEY → DEEPSEEK_API_KEY——多 key 环境（中转站 OPENAI key
            # + 官方 DEEPSEEK key）下官方 DeepSeek 会串 key → 401。
            # DeepSeek 官方必须优先 DEEPSEEK_API_KEY。
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        super().__init__(model=model, base_url=base_url, api_key=api_key,
                         timeout=timeout, max_retries=max_retries, _http=_http,
                         headers=headers, temperature=temperature)

    def name(self): return f"deepseek:{self.model}"

    def spec(self):
        ref = getattr(self, "_credential_ref", None)
        if self.base_url != "https://api.deepseek.com" or self._headers or ref:
            return {"type": "deepseek", "model": self.model, "base_url": self.base_url,
                    **({"headers": dict(self._headers)} if self._headers else {}),
                    **({"credential_ref": str(ref)} if ref else {})}
        return f"deepseek:{self.model}"

    def cache_capabilities(self) -> dict:
        """DeepSeek 无服务端 prompt 缓存机制——客户端缓存兜底。"""
        return {"server_prompt_cache": "none"}
