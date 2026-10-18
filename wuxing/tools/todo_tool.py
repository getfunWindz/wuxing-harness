"""E2-5 任务清单工具（`todo_write`）：模型侧临时自查清单（整表替换）。

纪律（计划 `docs/plans/2026-10-03-wuxing-todo-list.md`）：
- **整表替换**：每次调用传全表——无部分更新 / 无读回 / 无删除工具；
- **非判定**：不参与完成判定 / 契约校验 / 验收——完成仍以物证 + verify 为准；
- **单所有者**：状态存活于本工具实例（per-run 引擎天然隔离；runner 在单元
  开始调用 `reset()` 清空——防跨单元串表）；
- 上限：≤20 项，content ≤200 字符（非法值 loud 拒绝并指明条目序号）。
"""
from wuxing.protocols import Tool, ToolResult

MAX_TODO_ITEMS = 20
MAX_TODO_ITEM_CHARS = 200
_STATUSES = ("pending", "in_progress", "completed")


class TodoWriteTool(Tool):
    """单元内任务清单（整表替换；非判定）。"""

    def __init__(self):
        self.items: list = []  # run 作用域状态（runner 在单元开始 reset）

    def name(self):
        return "todo_write"

    def description(self):
        return ("更新本单元的自查清单（整表替换：每次传全表，不做部分更新）。"
                "多步工作时用它保持进度自组织；状态 pending/in_progress/completed。"
                "**清单不参与完成判定、不代表计划变更**——完成仍以落盘物证与验证为准；"
                f"短表优先（≤{MAX_TODO_ITEMS} 项，每项一行 ≤{MAX_TODO_ITEM_CHARS} 字符）。")

    def input_schema(self):
        return {"type": "object",
                "properties": {"items": {"type": "array",
                                         "items": {"type": "object"}}},
                "required": ["items"]}

    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": False, "destructive": False}

    def reset(self):
        """单元开始清空（防跨单元串表——runner `_init_unit_runtime` 调用）。"""
        self.items = []

    def execute(self, items=None, **kw):
        err = self._validate(items)
        if err:
            return ToolResult(status="error", tool_name=self.name(), error=err)
        self.items = [{"content": str(it.get("content")).strip(),
                       "status": str(it.get("status"))} for it in items]
        return ToolResult(status="ok", tool_name=self.name(),
                          content=f"清单已更新：{len(self.items)} 项")

    @staticmethod
    def _validate(items) -> str:
        """loud 校验：返回错误文案（空串=合法）；不得静默接受非法表。"""
        if not isinstance(items, list):
            return "param: items 必须为数组"
        if len(items) > MAX_TODO_ITEMS:
            return f"items 超出上限（{len(items)} > {MAX_TODO_ITEMS} 项）"
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                return f"items[{i}] 必须为对象"
            status = it.get("status")
            if status not in _STATUSES:
                return (f"items[{i}].status 非法：{status!r}"
                        f"（合法值：{' / '.join(_STATUSES)}）")
            content = it.get("content")
            if not isinstance(content, str) or not content.strip():
                return f"items[{i}].content 不能为空"
            if len(content) > MAX_TODO_ITEM_CHARS:
                return (f"items[{i}].content 超长"
                        f"（{len(content)} > {MAX_TODO_ITEM_CHARS} 字符）")
        return ""
