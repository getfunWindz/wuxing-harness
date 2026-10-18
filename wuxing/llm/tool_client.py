"""ToolCallingLlm（P5：原生 function calling——不再文本协议）。

LLM 调用原生 tools 参数（OpenAI 兼容格式），返回 ToolCallResult：
  text（正文） + tool_calls（结构化工具申请）。
若底层 LLM 不支持 tools 参数（多为 mock）→ 文本协议回退（deprecated 保留兼容）。
"""
import re

from wuxing.llm.base import BaseLlmProvider
from wuxing.llm.tool_results import ToolCallResult

_TOOLCALL_RE = re.compile(r"^TOOLCALL:(\w+)(.*)$")
_KV_RE = re.compile(r"(\w+)=(\S+)")

class ToolCallingLlm(BaseLlmProvider):
    def __init__(self, inner, tools_desc):
        self._inner = inner
        self._tools_desc = tools_desc  # callable → [{"name","description","input_schema"}]
        self.call_count = 0
    def name(self): return f"toolcall:{self._inner.name()}"

    def spec(self) -> str:
        """剥壳：toolcall: 前缀不可回构——记录内层 spec。"""
        return self._inner.spec()
    def chat(self, messages: list) -> ToolCallResult:
        self.call_count += 1
        tools = self._infer_schema(self._tools_desc())
        try:
            raw = self._inner.chat(messages, tools=tools)
        except TypeError:
            return self._chat_text_fallback(messages)
        if isinstance(raw, ToolCallResult):
            return raw
        return self._parse_text(raw)

    @staticmethod
    def _infer_schema(tools):
        return [{"type": "function",
                 "function": {"name": t["name"],
                              "description": t.get("description", ""),
                              "parameters": t.get("input_schema", {"type": "object"})}}
                for t in tools]

    def _chat_text_fallback(self, messages: list) -> ToolCallResult:
        """底层不支持原生 tools → 旧文本协议（system 注入说明 + 解析 TOOLCALL 行）。"""
        schema = self._tools_desc()
        tool_block = "\n".join(
            f"- {t['name']}: {t['description']} (参数: {t['input_schema']})"
            for t in schema)
        system = {
            "role": "system",
            "content": ("你可以调用工具。需要工具时，输出一行："
                        "TOOLCALL:<工具名> 参数=值 ... （参数用空格分隔，值不加引号），"
                        "然后继续输出内容。可用工具：\n" + tool_block),
        }
        raw = self._inner.chat([system] + messages)
        return self._parse_text(raw)

    def _parse_text(self, raw: str) -> ToolCallResult:
        """文本协议解析：TOOLCALL 行 → tool_calls；其余 → text。"""
        tool_calls = []
        text_parts = []
        for line in raw.splitlines():
            m = _TOOLCALL_RE.match(line.strip())
            if m:
                name, rest = m.group(1), m.group(2)
                kwargs = {k: v for k, v in _KV_RE.findall(rest)}
                tool_calls.append({"name": name, "arguments": kwargs})
            else:
                text_parts.append(line)
        return ToolCallResult(text="\n".join(text_parts), tool_calls=tool_calls)
