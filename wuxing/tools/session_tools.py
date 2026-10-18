"""会话检索工具（Task C1）：模型可用的工作区历史搜索（DSH session_search 对标）。

范围=当前工作区 `<root>/.wuxing/*.jsonl`（排除内部 jsonl）；首期子串匹配
（大小写不敏感）；结构化返回 会话文件 · 第N轮 · 角色/字段 · 片段；只读。
"""
import json
import pathlib

from wuxing.protocols import Tool, ToolResult

# 与壳侧 api_routes/base._INTERNAL_JSONL 同口径（引擎不依赖壳层——独立维护；
# 一致性由测试守住：wuxing/tests/test_session_tools.py 断言两集合相等）
_INTERNAL_JSONL = {"provenance.jsonl", "trace.jsonl", "unit-bindings.jsonl",
                   "context-edits.jsonl", "branches.jsonl", "tickets.jsonl"}


class SessionSearchTool(Tool):
    """搜索本工作区历史会话（.wuxing 会话记录；只读）。"""

    def __init__(self, ws, max_results: int = 10):
        self._ws = ws
        self._max = max(1, int(max_results))

    def name(self):
        return "session_search"

    def description(self):
        return ("搜索本工作区历史会话（.wuxing 会话记录）：返回 会话文件 · 轮次 · "
                "片段；用于回看之前的任务与结论（只读，默认前 10 条）。")

    def input_schema(self):
        return {"type": "object", "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"}}, "required": ["query"]}

    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": False, "destructive": False}

    def execute(self, query="", limit=0, **kw):
        q = str(query or "").strip()
        if not q:
            return ToolResult(status="error", tool_name=self.name(),
                              error="empty query")
        cap = int(limit or 0) or self._max
        base = pathlib.Path(self._ws.root) / ".wuxing"
        outs = []
        if base.is_dir():
            for p in sorted(base.glob("*.jsonl")):
                if p.name in _INTERNAL_JSONL:
                    continue
                try:
                    lines = p.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                for ln in reversed(lines):          # 新轮次优先
                    if len(outs) >= cap:
                        break
                    try:
                        row = json.loads(ln)
                    except ValueError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    for field, label in (("user_text", "用户"),
                                         ("reply", "回复"),
                                         ("summary", "小结")):
                        text = str(row.get(field) or "")
                        if q.lower() not in text.lower():
                            continue
                        i = text.lower().find(q.lower())
                        snip = text[max(0, i - 60):i + len(q) + 90]
                        outs.append(
                            f"{p.name} · 第{row.get('round', '?')}轮 · "
                            f"{label}：…{snip}…")
                        break
                if len(outs) >= cap:
                    break
        if not outs:
            return ToolResult(status="ok", tool_name=self.name(),
                              content="No matching history found")
        return ToolResult(status="ok", tool_name=self.name(),
                          content="\n".join(outs))
