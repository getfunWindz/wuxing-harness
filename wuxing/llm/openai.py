"""OpenAI 兼容 Provider（P4.5：base_url 泛化——DeepSeek/OpenAI/Ollama/vLLM 等全兼容）。

OpenAIChatProvider:      POST {base}/chat/completions（P4 DeepSeek 的泛化）
OpenAIResponsesProvider: POST {base}/responses（OpenAI 新 Responses API）
"""
import os

import requests

from wuxing.llm.base import BaseLlmProvider

_TEMP_SEQ = [0.0, 0.3, 0.6, 0.9]

class OpenAIChatProvider(BaseLlmProvider):
    """OpenAI 兼容 chat/completions（任意 base_url——DeepSeek/OpenAI/vLLM/Ollama...）。

    延迟校验：构造时不检查 key（工厂/配置阶段可随意构造）；
    首次 chat() 时若无 key 则抛 RuntimeError（明确失败而非静默）。
    """
    def __init__(self, model="deepseek-chat", base_url="https://api.deepseek.com",
                 api_key=None, timeout=60.0, max_retries=2, _http=None, headers=None,
                 temperature=0.0):
        super().__init__(max_retries=max_retries)
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "") or \
            os.environ.get("DEEPSEEK_API_KEY", "")
        self.timeout = timeout
        self._http = _http or requests
        self._headers = dict(headers or {})  # 中转站网关自定义头（User-Agent 等）
        self._temperature = temperature  # None = 省略字段（kimi 类模型拒绝 temperature）
        # Pi 同款（2026-09-10）：会话亲和缓存键（引擎设置——会话/工作区标识）
        self._cache_key = ""

    def name(self): return f"openai-compat:{self.model}"

    def spec(self):
        """完整可回构：base_url 非规范默认 / 自定义头 / 凭据引用 → dict。"""
        ref = getattr(self, "_credential_ref", None)
        if self.base_url != "https://api.openai.com/v1" or self._headers or ref:
            return {"type": "openai", "model": self.model, "base_url": self.base_url,
                    **({"headers": dict(self._headers)} if self._headers else {}),
                    **({"credential_ref": str(ref)} if ref else {})}
        return f"openai:{self.model}"

    def cache_capabilities(self) -> dict:
        """P10 E4：OpenAI 兼容系支持自动前缀缓存（prompt_cache_key/session 亲和）。"""
        return {"server_prompt_cache": "openai-completions"}

    def build_payload(self, prefix_parts: list, tools: list | None = None) -> dict:
        """P10 E1：构建请求载荷——OpenAI 兼容前缀缓存键（prompt_cache_key）。

        none 能力（如 DeepSeek）零注入（继承默认）。
        """
        payload = {"model": self.model, "temperature": 0.0}
        if self.cache_capabilities()["server_prompt_cache"] == "openai-completions":
            import hashlib
            stable = "|".join(prefix_parts)
            payload["prompt_cache_key"] = hashlib.sha256(
                stable.encode("utf-8")).hexdigest()
        return payload

    def chat(self, messages, tools: list | None = None):
        if not self.api_key and self._http is requests:
            raise RuntimeError("未配置 API key（OPENAI_API_KEY 或构造/api_key 参数）")
        # P12：退避重试（抖动）+ 温度递增（重试多样性——golden_ratio 经验）
        attempts = []

        def _temp_for(attempt: int):
            # B 级修复（2026-09-11 审查）：显式 temperature（如 0.7）首轮生效——
            # 此前被重试序列覆盖（配置失效）；重试不降低配置值（取 max）；
            # None（kimi 类）仍始终省略字段
            if self._temperature is None:
                return None
            if attempt == 0:
                return self._temperature
            return max(self._temperature,
                       _TEMP_SEQ[min(attempt, len(_TEMP_SEQ) - 1)])

        def _once():
            attempt = len(attempts)
            attempts.append(attempt)
            return self._chat_raw(messages, _temp_for(attempt), tools)

        return self._retry_with_backoff(_once)

    def _chat_raw(self, messages, temperature, tools=None):
        payload = {"model": self.model, "messages": messages,
                   "temperature": temperature}
        if temperature is None:
            payload.pop("temperature")  # kimi 类模型：字段省略（拒绝 400）
        if tools:
            payload["tools"] = tools
        # Pi 同款（2026-09-10）：会话亲和缓存键注入（clamp 64 字符——OpenAI 限制）
        if self._cache_key:
            payload["prompt_cache_key"] = "".join(list(self._cache_key)[:64])
        resp = self._http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json", **self._headers},
            json=payload,
            timeout=self.timeout)
        resp.raise_for_status()
        resp_http = resp.json()
        msg = resp_http["choices"][0]["message"]
        # 思维链（2026-09-11 观测增强）：DeepSeek-flash thinking 模型返回
        # reasoning_content——线程内暂存，由 runner 落 trace（不改变模型输入）
        _rc = msg.get("reasoning_content") or msg.get("reasoning") or ""
        if _rc:
            self._record_reasoning(_rc)
        # P1 T1：usage 真值解析（债 1）——OpenAI official: prompt_tokens_details.cached_tokens；
        # DeepSeek 兼容: prompt_cache_hit_tokens（顶层）
        u = resp_http.get("usage") or {}
        cache_read = 0
        details = u.get("prompt_tokens_details")
        if isinstance(details, dict):
            cache_read = details.get("cached_tokens", 0)
        else:
            cache_read = u.get("prompt_cache_hit_tokens", 0)
        # DeepSeek 官方口径（2026-09-10 用户要求·读官方文档）：直接问询 API——
        # prompt_cache_hit_tokens（命中）+ prompt_cache_miss_tokens（未命中）双字段
        # （命中率 = hit/(hit+miss) 官方定义）；官方响应含 miss 字段（2026-09-11
        # 探测确认）；部分兼容通道缺该字段时按官方恒等式推导兜底：
        # prompt_tokens = prompt_cache_hit_tokens + prompt_cache_miss_tokens
        cache_miss = u.get("prompt_cache_miss_tokens")
        _pt = int(u.get("prompt_tokens", 0) or 0)
        if cache_miss is None and _pt > 0:
            cache_miss = max(0, _pt - int(cache_read or 0))
        # 思维链 token（thinking 模型）：completion_tokens_details.reasoning_tokens
        _ctd = u.get("completion_tokens_details")
        _rt = _ctd.get("reasoning_tokens") if isinstance(_ctd, dict) else None
        self._record_usage({"input": u.get("prompt_tokens", 0),
                            "output": u.get("completion_tokens", 0),
                            "cache_read": cache_read, "cache_write": 0,
                            **({"cache_miss": cache_miss}
                               if cache_miss is not None else {}),
                            **({"reasoning_tokens": _rt}
                               if _rt is not None else {})})
        # 原生 tool_calls：结构化返回
        if msg.get("tool_calls"):
            from wuxing.llm.tool_results import ToolCallResult
            calls = []
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                import json as _json
                try:
                    args = _json.loads(fn.get("arguments", "{}"))
                except Exception:
                    args = {}
                calls.append({"name": fn.get("name", ""), "arguments": args})
            return ToolCallResult(text=msg.get("content") or "", tool_calls=calls)
        return msg.get("content", "")


class OpenAIResponsesProvider(BaseLlmProvider):
    """OpenAI Responses API（POST /responses；output[].content[].text 解析）。"""
    def __init__(self, model="gpt-4o-mini", base_url="https://api.openai.com/v1",
                 api_key=None, timeout=60.0, max_retries=2, _http=None):
        super().__init__(max_retries=max_retries)
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key and _http is None:
            raise RuntimeError("未配置 OPENAI_API_KEY")
        self.timeout = timeout
        self._http = _http or requests
        # 流式降级/断流原因（chat_stream——""=无异常）
        self.last_stream_error = ""
        # v43-⑤：流式不支持缓存（端点 400 类错误一次后不再重试——降噪）
        self._stream_unsupported = False

    def name(self): return f"openai-responses:{self.model}"

    def spec(self):
        """可回构 spec（2026-10-01 P1 修复）。

        缺此方法时基类回退 name()（openai-responses:…）——该字符串无法被
        create_provider 回构（未知 provider type）；一旦记入智脑记忆，
        下一个相似任务命中强证据即失败。与 openai/deepseek/anthropic 同款口径；
        凭据引用（credential_ref/api_key_env）必须随 spec 回构（否则回构丢 key）。
        """
        ref = getattr(self, "_credential_ref", None)
        if self.base_url != "https://api.openai.com/v1" or ref:
            return {"type": "responses", "model": self.model,
                    "base_url": self.base_url,
                    **({"credential_ref": str(ref)} if ref else {})}
        return f"responses:{self.model}"

    def chat(self, messages, tools: list | None = None):
        if not self.api_key and self._http is requests:
            raise RuntimeError("未配置 OPENAI_API_KEY")
        payload = self._build_payload(messages, tools)
        for attempt in range(self.max_retries + 1):
            self.call_count += 1
            try:
                resp = self._http.post(
                    f"{self.base_url}/responses",
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json"},
                    json=payload,
                    timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                # usage：input_tokens（含命中）/ cached_tokens / reasoning_tokens
                self._record_responses_usage(data.get("usage") or {})
                # output 解析：思维链 / 函数调用 / 文本（chat_stream 共用同一解析器）
                texts, calls, reasonings = self._parse_output_blocks(
                    data.get("output"))
                if reasonings:
                    self._record_reasoning("\n".join(reasonings))
                text = "\n".join(t for t in texts if t)
                if calls:
                    from wuxing.llm.tool_results import ToolCallResult
                    return ToolCallResult(text=text, tool_calls=calls)
                return text if text else "(empty response)"
            except (requests.RequestException, OSError):
                if attempt < self.max_retries:
                    continue
                raise

    def _build_payload(self, messages, tools: list | None = None) -> dict:
        """Responses 请求载荷（chat 与 chat_stream 共用——防两路漂移）。"""
        payload = {
            "model": self.model,
            "input": [m for m in messages if m.get("role") != "system"],
            "instructions": "\n".join(
                m["content"] for m in messages if m.get("role") == "system"),
        }
        if tools:
            # 黄金测试阻断修复（2026-09-30）：Responses 工具为**扁平**格式
            # （name/description/parameters 顶层；不同于 chat-completions 嵌套 function）
            payload["tools"] = [
                {"type": "function",
                 "name": str((t.get("function") or {}).get("name") or ""),
                 "description": str((t.get("function") or {}).get(
                     "description") or ""),
                 "parameters": (t.get("function") or {}).get("parameters")
                 or {"type": "object", "properties": {}}}
                for t in tools]
        return payload

    def _record_responses_usage(self, u) -> None:
        """usage 落账（chat 与 chat_stream 共用）：input_tokens（含命中）/
        cached_tokens / reasoning_tokens。"""
        if not (isinstance(u, dict) and u):
            return
        det = u.get("input_tokens_details") or {}
        try:
            cache_read = int((det or {}).get("cached_tokens") or 0)
        except (TypeError, ValueError):
            cache_read = 0
        odet = u.get("output_tokens_details") or {}
        rt = (odet or {}).get("reasoning_tokens")
        self._record_usage({
            "input": u.get("input_tokens", 0),
            "output": u.get("output_tokens", 0),
            "cache_read": cache_read, "cache_write": 0,
            **({"reasoning_tokens": rt} if rt is not None else {})})

    @staticmethod
    def _parse_output_blocks(output) -> tuple:
        """output[] → (texts, calls, reasonings)（chat 与 chat_stream 共用）。

        形状兼容：OpenAI summary[].text / DeepSeek content[].reasoning_text；
        function_call → {"name", "arguments": dict}（与 chat() 返回结构一致）。
        """
        import json as _json
        texts: list = []
        calls: list = []
        reasonings: list = []
        for block in output or []:
            if not isinstance(block, dict):
                continue
            btype = str(block.get("type") or "")
            if btype == "function_call":
                try:
                    args = _json.loads(block.get("arguments") or "{}")
                except (TypeError, ValueError):
                    args = {}
                calls.append({"name": str(block.get("name") or ""),
                              "arguments": args
                              if isinstance(args, dict) else {}})
                continue
            if btype == "reasoning":
                # OpenAI：summary[].text；DeepSeek Responses：content[].reasoning_text
                for s in block.get("summary") or []:
                    if isinstance(s, dict) and s.get("text"):
                        reasonings.append(str(s["text"]))
                for c in block.get("content") or []:
                    if (isinstance(c, dict)
                            and c.get("type") == "reasoning_text"
                            and c.get("text")):
                        reasonings.append(str(c["text"]))
                continue
            for c in block.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "output_text":
                    texts.append(str(c.get("text") or ""))
        return texts, calls, reasonings

    def supports_stream(self) -> bool:
        """v43-⑤：流式能力（端点不支持后缓存为 False——引擎据此跳过无效尝试）。"""
        return not self._stream_unsupported

    def chat_stream(self, messages, tools: list | None = None, on_delta=None):
        """SSE 流式调用（思维链实时化；返回与 chat() 同构）。

        on_delta(kind, text)：增量回调——kind ∈ {"reasoning","text"}。
        降级纪律（不静默，原因落 last_stream_error）：
        - 假体/网关不支持流式（TypeError / 无 iter_lines / HTTP 拒绝）→ 回退 chat()；
        - 流中途超时/断连 → 已收内容按现状返回（思维链/文本/工具尽力组装）。
        """
        if not self.api_key and self._http is requests:
            raise RuntimeError("未配置 OPENAI_API_KEY")
        import json as _json
        self.last_stream_error = ""
        if self._stream_unsupported:
            self.last_stream_error = "stream unsupported (cached skip)"
            return self.chat(messages, tools)
        payload = self._build_payload(messages, tools)
        payload["stream"] = True
        try:
            resp = self._http.post(
                f"{self.base_url}/responses",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json=payload, timeout=self.timeout, stream=True)
        except TypeError as exc:
            self.last_stream_error = f"TypeError: {exc}"
            return self.chat(messages, tools)
        except (requests.RequestException, OSError) as exc:
            self.last_stream_error = f"{type(exc).__name__}: {exc}"
            return self.chat(messages, tools)
        if not hasattr(resp, "iter_lines"):
            self.last_stream_error = "streaming unsupported: response has no iter_lines"
            return self.chat(messages, tools)
        try:
            resp.raise_for_status()
        except (requests.RequestException, OSError) as exc:
            self.last_stream_error = f"{type(exc).__name__}: {exc}"
            _status = getattr(getattr(exc, "response", None), "status_code", None)
            if _status in (400, 404, 405, 415, 422, 501):
                # v43-⑤：端点明确拒绝流式 → 缓存（后续零无效请求）
                self._stream_unsupported = True
            return self.chat(messages, tools)

        self.call_count += 1
        reasoning_parts: list = []
        text_parts: dict = {}
        text_order: list = []
        args_parts: dict = {}
        calls: list = []
        completed_output = None
        completed_usage = None

        def _emit(kind: str, text: str) -> None:
            if on_delta is not None and text:
                on_delta(kind, text)

        try:
            for raw in resp.iter_lines():
                line = raw.decode("utf-8", "replace") if isinstance(
                    raw, (bytes, bytearray)) else str(raw or "")
                if (not line) or line.startswith((":", "event:")):
                    continue
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    evt = _json.loads(data_str)
                except (TypeError, ValueError):
                    continue
                if not isinstance(evt, dict):
                    continue
                etype = str(evt.get("type") or "")
                if etype == "response.reasoning_text.delta":
                    delta = str(evt.get("delta") or "")
                    if delta:
                        reasoning_parts.append(delta)
                        _emit("reasoning", delta)
                elif etype == "response.output_text.delta":
                    delta = str(evt.get("delta") or "")
                    if delta:
                        iid = str(evt.get("item_id") or "")
                        if iid not in text_parts:
                            text_parts[iid] = []
                            text_order.append(iid)
                        text_parts[iid].append(delta)
                        _emit("text", delta)
                elif etype == "response.function_call_arguments.delta":
                    delta = str(evt.get("delta") or "")
                    if delta:
                        args_parts.setdefault(
                            str(evt.get("item_id") or ""), []).append(delta)
                elif etype == "response.output_item.done":
                    item = evt.get("item")
                    if (isinstance(item, dict)
                            and item.get("type") == "function_call"):
                        raw_args = item.get("arguments")
                        if raw_args is None:
                            iid = str(item.get("id")
                                      or evt.get("item_id") or "")
                            raw_args = "".join(args_parts.get(iid, []))
                        try:
                            args = _json.loads(raw_args or "{}")
                        except (TypeError, ValueError):
                            args = {}
                        calls.append({"name": str(item.get("name") or ""),
                                      "arguments": args
                                      if isinstance(args, dict) else {}})
                elif etype == "response.completed":
                    r = evt.get("response")
                    if isinstance(r, dict):
                        completed_output = r.get("output")
                        completed_usage = r.get("usage") or {}
                elif etype in ("response.failed", "response.incomplete"):
                    r = evt.get("response")
                    r = r if isinstance(r, dict) else {}
                    err = r.get("error")
                    err = err if isinstance(err, dict) else {}
                    self.last_stream_error = str(
                        err.get("message") or err.get("code") or etype)
        except (requests.RequestException, OSError) as exc:
            self.last_stream_error = f"{type(exc).__name__}: {exc}"

        # usage：completed 全量响应落账（与 chat() 同款——共享解析器）
        if isinstance(completed_usage, dict) and completed_usage:
            self._record_responses_usage(completed_usage)
        # 文本/工具/思维链：增量累积优先；缺失面用 completed 全量兜底
        text = "\n".join(
            "".join(text_parts[i]) for i in text_order if text_parts[i])
        reasoning = "".join(reasoning_parts)
        if completed_output is not None and (not text or not calls
                                             or not reasoning):
            f_texts, f_calls, f_reasonings = self._parse_output_blocks(
                completed_output)
            if not text:
                text = "\n".join(t for t in f_texts if t)
            if not calls:
                calls = f_calls
            if not reasoning:
                reasoning = "\n".join(f_reasonings)
        if reasoning:
            self._record_reasoning(reasoning)
        if calls:
            from wuxing.llm.tool_results import ToolCallResult
            return ToolCallResult(text=text, tool_calls=calls)
        return text if text else "(empty response)"
