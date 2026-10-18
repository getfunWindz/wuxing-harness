"""ToolSearch 式工具检索（E3-3 · X6 Phase 1）：延迟加载工具的发现通道。

语义：只检索 `deferred=True` 的工具（MCP 延迟池）；词法评分（名称权重高于描述）；
结果 = 名称 + 描述（≤2048 字符截断）+ 参数 schema。空 query = 按名列前 N（列表模式）。
披露面工具：不改变白名单/守卫/权限链——执行面仍由既有机制裁决（直呼已知工具名
不因此被阻断；本工具只解决「不知道有哪些工具」）。
"""
import json

from wuxing.protocols import Tool, ToolResult

_DESC_TRUNC = 2048   # CC 工具描述/instructions 默认截断口径（调研 §2.3）
_MAX_LIMIT = 20


def _tokens(text) -> list:
    return [t for t in str(text or "").lower().replace("_", " ").split() if t]


def _score(query: str, name: str, desc: str) -> int:
    """小写子串计次：名称命中权重 3 / 描述命中权重 1；整串额外加权。"""
    q = str(query or "").lower().strip()
    if not q:
        return 0
    n = str(name or "").lower()
    d = str(desc or "").lower()
    score = 0
    for p in (_tokens(q) or [q]):
        if not p:
            continue
        score += 3 * n.count(p)
        score += d.count(p)
    if q in n:
        score += 3
    if q in d:
        score += 1
    return score


class ToolSearchTool(Tool):
    """`tool_search`：检索延迟加载工具（约 5 条/次；空 query 列表模式）。"""

    def __init__(self, registry):
        self._registry = registry

    def name(self): return "tool_search"

    def description(self):
        return ("检索延迟加载的 MCP 工具（按关键词返回名称/说明/参数）："
                "先用本工具找到工具名，再直接调用该工具")

    def input_schema(self):
        return {"type": "object", "properties": {
            "query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": []}

    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": False, "destructive": False}

    def execute(self, query="", limit=5, **kw):
        try:
            lim = max(1, min(int(limit or 5), _MAX_LIMIT))
        except (TypeError, ValueError):
            lim = 5
        pool = [t for t in (self._registry.list() if self._registry else [])
                if getattr(t, "deferred", False)]
        q = str(query or "").strip()
        if q:
            scored = [(_score(q, t.name(), t.description()), t.name(), t)
                      for t in pool]
            scored = [x for x in scored if x[0] > 0]
            scored.sort(key=lambda x: (-x[0], x[1]))
            picks = [x[2] for x in scored[:lim]]
        else:
            picks = sorted(pool, key=lambda t: t.name())[:lim]
        if not picks:
            return ToolResult(
                status="ok", tool_name=self.name(),
                content="未找到匹配的延迟加载工具"
                        + (f"（查询：{q}）" if q else ""))
        lines = [f"找到 {len(picks)} 个延迟加载工具："]
        for t in picks:
            desc = str(t.description() or "")
            if len(desc) > _DESC_TRUNC:
                desc = desc[:_DESC_TRUNC] + "…"
            try:
                schema = json.dumps(t.input_schema(), ensure_ascii=False)
            except Exception:
                schema = "{}"
            lines.append(f"- {t.name()}: {desc}\n  参数: {schema}")
        lines.append("提示：直接以工具名调用（参数按上列 schema）。")
        return ToolResult(status="ok", content="\n".join(lines),
                          tool_name=self.name())
