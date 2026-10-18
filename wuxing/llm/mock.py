"""MockLlmProvider：确定性（P1 闭环；P4 换成 DeepSeek 实现，接口不变）。

P0 T3：输出带物证（写/读工具调用）——域契约硬化后纯文本不再通过 execute/verify。
"""
from wuxing.llm.base import BaseLlmProvider
from wuxing.llm.tool_results import ToolCallResult


class MockLlmProvider(BaseLlmProvider):
    def spec(self) -> str:
        return "mock"  # 默认 name()="MockLlmProvider" 不可回构

    def supports_native_tools(self) -> bool:
        return False  # mock 输出文本（TOOLCALL 行解析路径——文本协议兜底）

    def chat(self, messages, tools: list | None = None):
        self.call_count += 1
        # P1 T1：调用记录（usage 未知 → 全 0 条目——调用计数口径一致）
        self._record_usage(None)
        # P0 闭环：messages 已历史化——全量拼接检测（system 域标记 或 旧 user 前缀）
        # P0 T3：mock 输出带物证（写/读工具调用）——域契约硬化后纯文本不再能通过
        text = " ".join(m.get("content", "") for m in messages)
        if "域：plan" in text or "plan:" in text:
            return ToolCallResult(
                text=("实施工作流：\n- 工作流：docs——方案产物与文档（mock 契约）\n"
                      "方案：1. 收集信息 2. 产出内容 3. 校验\n验收标准：内容完整"),
                tool_calls=[{"name": "write_artifact", "arguments": {
                    "path": "mock-plan.md", "kind": "plan",
                    "content": ("实施工作流：\n- 工作流：docs——方案产物与文档\n"
                                "方案内容：1. 收集信息 2. 产出内容 3. 校验")}}])
        if "域：execute" in text or "execute:" in text:
            return ToolCallResult(
                text="执行成果：已完成。产物：result.md",
                tool_calls=[{"name": "write_artifact", "arguments": {
                    "path": "mock-result.md", "kind": "result",
                    "content": "执行成果：已完成"}}])
        if "域：verify" in text or "verify:" in text:
            return ToolCallResult(
                text="评审结论：通过。理由：产物满足验收标准",
                tool_calls=[{"name": "read_dependency",
                             "arguments": {"path": "mock-result.md"}}])
        return "（mock 响应）已处理：" + text[:50]
