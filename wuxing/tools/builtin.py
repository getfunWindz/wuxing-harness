"""内置工具（P1 最小集：write_artifact / read_dependency——热路径本地直调，不走进程代理）。"""
from wuxing.protocols import Artifact, Tool
from wuxing.workspace import Workspace


class WriteArtifactTool(Tool):
    def __init__(self, ws: Workspace):
        self._ws = ws
    def name(self): return "write_artifact"
    def description(self): return "向工作区写入产物文件（路径计入产物清单——可追踪物证）"
    def input_schema(self): return {"type": "object", "properties": {
        "path": {"type": "string"}, "kind": {"type": "string"},
        "content": {"type": "string"}}, "required": ["path", "content"]}
    def permission(self):
        return {"read": False, "write": True, "execute": False,
                "network": False, "destructive": False}

    def execute(self, path="", kind="", content="", **kw):
        from wuxing.protocols import ToolResult
        try:
            self._ws.write_artifact(Artifact(path=path, kind=kind), content)
            return ToolResult(status="ok", content=f"written {path}", tool_name=self.name())
        except ValueError as e:
            return ToolResult(status="blocked", tool_name=self.name(), error=str(e))

class ReadDependencyTool(Tool):
    def __init__(self, ws: Workspace):
        self._ws = ws
    def name(self): return "read_dependency"
    def description(self): return "读取依赖产物内容"
    def input_schema(self): return {"type": "object", "properties": {
        "path": {"type": "string"}}, "required": ["path"]}
    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": False, "destructive": False}

    def execute(self, path="", **kw):
        from wuxing.protocols import ToolResult
        content = self._ws.read(path)
        return ToolResult(status="ok",
                          content=content if content is not None else f"(missing: {path})",
                          tool_name=self.name())

def BUILTIN_TOOLS(ws: Workspace) -> list:
    return [WriteArtifactTool(ws), ReadDependencyTool(ws)]
