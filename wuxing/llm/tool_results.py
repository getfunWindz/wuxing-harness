"""工具调用结果（P5：原生 function calling 结构化返回）。"""
from dataclasses import dataclass, field


@dataclass
class ToolCallResult:
    text: str = ""
    tool_calls: list = field(default_factory=list)  # [{"name", "arguments": dict}]
