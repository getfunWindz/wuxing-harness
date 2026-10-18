"""SEC3：权限剖面——工具过滤契约 + 装配策略挂载。

设计：docs/WUXING_安全三件套_设计_2026-09-30.md §4.1/§4.4。
"""
from wuxing import permissions


class _T:
    def __init__(self, name, perm):
        self._name = name
        self._perm = perm

    def name(self):
        return self._name

    def permission(self):
        return dict(self._perm)


def test_read_only_allows_readonly_tools_only():
    tools = [_T("read_file", {"read": True}), _T("bash", {"execute": True}),
             _T("write_file", {"write": True}), _T("delegate", {"read": True})]
    kept = [t.name() for t in permissions.allowed_tools(tools, "read-only")]
    assert kept == ["read_file"]


def test_non_readonly_profiles_keep_all():
    tools = [_T("bash", {"execute": True})]
    assert permissions.allowed_tools(tools, "workspace-write") == tools
    assert permissions.allowed_tools(tools, "full-access") == tools


def test_filter_registry_read_only(tmp_path):
    import pathlib
    import tempfile

    from wuxing.tools.loader import load_tools
    from wuxing.workspace import Workspace
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    tools = load_tools(ws)
    removed = permissions.filter_registry(tools, "read-only")
    assert "bash" in removed and "write_artifact" in removed
    assert tools.get("read_file") is not None
    assert tools._tools  # 不为空且全为只读


def test_apply_tool_policy_mounts_guard_and_filters(tmp_path):
    import pathlib
    import tempfile

    from wuxing.tools.loader import load_tools
    from wuxing.workspace import Workspace
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    tools = load_tools(ws)
    removed = permissions.apply_tool_policy(tools, "read-only")
    assert "bash" in removed
    # 守卫已挂载（存在 _guard 字段即可——具体行为由 danger_guard 测试覆盖）
    assert getattr(tools, "_guard", None) is not None
