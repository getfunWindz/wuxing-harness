"""TDD：MCP 工具权限显式配置（最小权限——MCP 默认全 False 待显式声明解锁）。"""

from wuxing.protocols import ToolResult
from wuxing.skills import SkillRegistry  # noqa: F401 (依赖导入链验证)


class FakeToolAdapter:
    """模拟 McpToolAdapter（权限从 config 读取——与真实适配器同协议）。"""

    _PERM_KEYS = ("read", "write", "execute", "network", "destructive")

    def __init__(self, permissions: dict):
        self._perm = permissions

    def permission(self):
        perm = {"read": False, "write": False, "execute": False,
                "network": False, "destructive": False}
        for k in self._PERM_KEYS:
            if k in self._perm:
                perm[k] = bool(self._perm[k])
        return perm


def test_mcp_default_denies_all():
    """MCP 工具默认全 False（未显式声明 → 最小权限=拒绝）。"""
    t = FakeToolAdapter({})
    assert not any(t.permission().values())


def test_mcp_explicit_permissions_unlock():
    """显式配置解锁（如 read+write 供文档工具）。"""
    t = FakeToolAdapter({"read": True, "write": True})
    p = t.permission()
    assert p["read"] and p["write"] and not p["execute"]


def test_mcp_permissions_pass_registry_validation():
    """权限声明后可通过注册表校验（未声明被拦——既有机制联动）。"""
    from wuxing.tools.base import ToolRegistry

    class MyTool(FakeToolAdapter):
        def name(self): return "m_docs"
        def description(self): return "docs"
        def input_schema(self): return {"type": "object"}
        def execute(self, **kw): return ToolResult(status="ok", content="x")
        def permission(self):
            return {"read": True, "write": False, "execute": False,
                    "network": False, "destructive": False}

    reg = ToolRegistry([MyTool({})])
    res = reg.execute("m_docs")
    assert res.status == "ok", res.error
