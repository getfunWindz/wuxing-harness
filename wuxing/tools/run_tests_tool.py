"""run_tests：交付物测试运行（O2-1——verify/user 域沙箱执行能力）。

命令白名单（严格单命令；禁 shell 元字符）→ 复用 BashTool 沙箱执行路径
（native：cwd=工作区/敏感 env 剥离/超时杀树/尾部截断+G6；容器档同轴）。
物证：通过输出由 runner `_note_evidence` 记 `run_evidence`（与 bash 同源）。
"""
import re

from wuxing.protocols import Tool, ToolResult
from wuxing.tools.bash_tool import BashTool

# 仅允许 python[-3]/py 拉起 pytest/unittest；整条命令禁 shell 元字符与拼接
_RUN_TESTS_RE = re.compile(
    r"^(?:python3?|py) +-m +(?:pytest|unittest)(?: +[^\n;&|<>`$]*)?$")


class RunTestsTool(Tool):
    """交付物测试运行（白名单 + 沙箱复用；物证由 runner 统一累计）。"""

    def __init__(self, ws, timeout: float = 120.0, sandbox_enabled: bool = True,
                 sandbox_mode: str = "native", container_template: str = "",
                 shell_path: str = ""):
        self._bash = BashTool(
            ws, timeout=timeout, sandbox_enabled=sandbox_enabled,
            sandbox_mode=sandbox_mode, container_template=container_template,
            shell_path=shell_path)
        self._timeout = float(timeout)

    def name(self):
        return "run_tests"

    def description(self):
        return ("在沙箱内运行工作区交付物测试（不修改交付物）：仅允许单命令 "
                "`python -m pytest …` 或 `python -m unittest …`（禁拼接/管道/重定向）。"
                f"工作目录限定工作区；超时 {self._timeout:g}s 可传 timeout 覆盖（上限 600）；"
                "输出超限保留末尾并全文落盘。用于验收阶段实跑测试并留下运行物证。")

    def input_schema(self):
        return {"type": "object", "properties": {
            "command": {"type": "string",
                        "description": "测试命令（白名单：python -m pytest / python -m unittest）"},
            "timeout": {"type": "number", "minimum": 1, "maximum": 600}},
            "required": ["command"]}

    def permission(self):
        # 白名单 + 沙箱约束下的执行面；native 档写入无法 OS 级禁止（容器档可）
        return {"read": True, "write": False, "execute": True,
                "network": True, "destructive": True}

    def route_info(self):
        info = dict(self._bash.route_info())
        info["tool"] = "run_tests"
        return info

    def execute(self, command="", timeout=None, **kw):
        cmd = str(command or "").strip()
        if not cmd:
            return ToolResult(status="error", tool_name=self.name(),
                              error="param: command 不能为空")
        if not _RUN_TESTS_RE.match(cmd):
            return ToolResult(
                status="error", tool_name=self.name(),
                error="run_tests 仅允许单命令：`python -m pytest …` 或 "
                      "`python -m unittest …`（禁 shell 元字符/拼接/管道/重定向）")
        # 内部受控合并 stderr（unittest 成功摘要走 stderr；用户命令面仍禁元字符，
        # 附加段由工具控制——保证 OK/passed 摘要能进入运行物证）
        res = self._bash.execute(command=f"{cmd} 2>&1", timeout=timeout)
        return ToolResult(status=res.status, tool_name=self.name(),
                          content=res.content, error=res.error)
