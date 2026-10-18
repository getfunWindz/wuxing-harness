"""SEC3 权限剖面：工具装配过滤 + 统一策略挂载（设计 §4.1/§4.4）。

- read-only：只读工具集（`read=True` 且其余权限全假；扩展/MCP 同契约）；
- workspace-write / full-access：全量工具（路径/命令分档在 Workspace/danger_guard）；
- apply_tool_policy：装配期单点（主工具与 delegate 子工具同策略）。
"""
from __future__ import annotations

READ_ONLY_EXCLUDED = {"delegate"}  # 设计 §6.2：read-only 不含 delegate
_MUTATING = ("write", "execute", "network", "destructive")
PROFILES = ("read-only", "workspace-write", "full-access")


def tool_allowed_read_only(tool) -> bool:
    name = str(tool.name())
    if name in READ_ONLY_EXCLUDED:
        return False
    perm = dict(tool.permission() or {})
    if not perm.get("read"):
        return False
    return not any(perm.get(k) for k in _MUTATING)


def allowed_tools(tools, profile: str):
    if profile != "read-only":
        return list(tools)
    return [t for t in tools if tool_allowed_read_only(t)]


def filter_registry(registry, profile: str) -> list:
    """按剖面从注册表移除不允许的工具；返回被移除名列表。"""
    removed = []
    if profile != "read-only":
        return removed
    for name in list(getattr(registry, "_tools", {}).keys()):
        tool = registry._tools[name]
        if not tool_allowed_read_only(tool):
            registry._tools.pop(name, None)
            removed.append(name)
    return removed


def apply_tool_policy(registry, profile: str) -> list:
    """装配期统一策略：剖面过滤 + bash 守卫按剖面挂载。返回被移除工具名。"""
    from wuxing.danger_guard import check_command
    removed = filter_registry(registry, profile)
    registry.set_guard(lambda name, kwargs: (
        (check_command(kwargs.get("command", ""), profile=profile) or True)
        if name == "bash" else True))
    return removed
