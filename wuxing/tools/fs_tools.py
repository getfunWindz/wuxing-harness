"""内置文件工具（P2：真文件系统操作，沙箱 = 工作区内）。

路径逃逸守卫：任何解析后落在 Workdir 之外的路径一律拒绝（安全护栏）。
"""
import pathlib

from wuxing.atomic_write import atomic_write_text
from wuxing.protocols import Tool


class _SandboxedTool(Tool):
    """文件工具基类：持有工作区 + 路径解析（逃逸守卫单一来源）。"""
    def __init__(self, ws):
        self._ws = ws

    def _resolve(self, path: str) -> pathlib.Path | None:
        """路径解析（守卫单一来源：Workspace._safe_path——返回 None 表示不可达）。

        L4 真跑发现：错误语义透明——「internal file hidden / escapes workspace」
        原守卫消息统一转 not found（误导模型换路径重试——65 次同参重读循环）。
        """
        if not path:
            return None
        try:
            return self._ws._safe_path(path)
        except ValueError:
            return None  # 不可达（逃逸/内部数据）——消息由调用方语义化
class ReadFileTool(_SandboxedTool):
    def name(self): return "read_file"
    def description(self):
        return ("读取工作区内的文件内容（仅工作区内——越界拒绝）；"
                "大文件可用 offset（起始行，1 起）与 limit（行数）分段读取")
    def input_schema(self): return {"type": "object", "properties": {
        "path": {"type": "string"},
        "offset": {"type": "integer"},
        "limit": {"type": "integer"}}, "required": ["path"]}
    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": False, "destructive": False}

    def execute(self, path="", offset=0, limit=0, **kw):
        from wuxing.protocols import ToolResult
        p = self._resolve(path)
        if p is None:
            # L4：内部数据/逃逸语义化（原 not found 误导模型重试——65 次同参循环）
            low = (path or "").lower()
            if any(k in low for k in (".wuxing", "reply_cache", "shape_cache",
                                      "task_state", "manifest", "brain_memory")):
                return ToolResult(status="blocked", tool_name=self.name(),
                                  error=f"internal data hidden: {path}——引擎内部文件不可读，请勿重试")
            return ToolResult(status="blocked", tool_name=self.name(),
                              error=f"not found (outside workspace): {path}")
        if p.is_dir():
            # 冒烟根因3：LLM 读目录（猜路径）→ 结构化拒绝（不抛异常冲破引擎）
            return ToolResult(status="error", tool_name=self.name(),
                              error=f"is a directory: {path}")
        if p.exists():
            try:
                content = p.read_text(encoding="utf-8")
            except OSError as e:
                return ToolResult(status="error", tool_name=self.name(),
                                  error=f"{type(e).__name__}: {e}")
            try:
                off, lim = int(offset or 0), int(limit or 0)
            except (TypeError, ValueError):
                off, lim = 0, 0
            if off or lim:
                # D（2026-09-11）：分段读取——压缩的安全网（给能力，不给禁令）
                lines = content.splitlines(keepends=True)
                total = len(lines)
                start = max(0, off - 1)
                chunk = lines[start:start + lim] if lim > 0 else lines[start:]
                if not chunk:
                    return ToolResult(
                        status="ok", tool_name=self.name(),
                        content=f"(no lines: file has {total} lines, "
                                f"requested from {off})")
                body = (f"[lines {start + 1}-{start + len(chunk)} of {total}]\n"
                        + "".join(chunk))
                return ToolResult(status="ok", content=body,
                                  tool_name=self.name())
            return ToolResult(status="ok", content=content,
                              tool_name=self.name())
        return ToolResult(status="ok", content="not found", tool_name=self.name())

class WriteFileTool(_SandboxedTool):
    def name(self): return "write_file"
    def description(self):
        return "写入文件到工作区（自动创建父目录；原子写——先写临时文件再替换）"
    def input_schema(self): return {"type": "object", "properties": {
        "path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"]}
    def permission(self):
        return {"read": False, "write": True, "execute": False,
                "network": False, "destructive": False}

    def execute(self, path="", content="", **kw):
        from wuxing.protocols import ToolResult
        p = self._resolve(path)
        if p is None:
            return ToolResult(status="blocked", tool_name=self.name(),
                              error=f"path escapes workspace: {path}")
        try:
            atomic_write_text(p, str(content))
        except OSError as e:
            return ToolResult(status="error", tool_name=self.name(), error=str(e))
        return ToolResult(status="ok", content=f"written {path}", tool_name=self.name())
