"""Engine 扩展命令/MCP 子系统（骨架分期 P6/F-3e：自 engine.py 提取的方法组）。

来源：`wuxing/engine.py`（2026-10-06 迁移；方法体逐字节保持）。
理由：F-3 巨型文件分期——命令/MCP 面落隔离模块（S-2 mixin 裁定）；engine 只做类基接线。
依赖：经 `self` 访问引擎状态（_ext_result/tools/_mcp_cfgs/_mcp_pool）；**不得 import engine**（守卫）。
"""


class EngineCmdsMixin:
    def list_commands(self) -> list[dict]:
        """E2-3/E2-UI：扩展命令清单（壳命令面板/CLI 用；不含 handler）。"""
        return [{"name": c["name"], "description": c["description"],
                 "source": c["source"], "args": list(c.get("args") or [])}
                for c in self._ext_result.commands]

    def run_command(self, name, args=None) -> dict:
        """E2-3/E2-UI：执行扩展命令（未知 → KeyError；参数校验/转换后交 handler）。"""
        cmd = next((c for c in self._ext_result.commands
                    if c["name"] == str(name)), None)
        if cmd is None:
            raise KeyError(f"未知扩展命令：{name}")
        from wuxing.extensions import coerce_command_args
        coerced, err = coerce_command_args(cmd.get("args") or [], dict(args or {}))
        if err:
            return {"status": "error", "text": "", "error": err}
        try:
            res = cmd["handler"](coerced)
        except Exception as exc:
            return {"status": "error", "text": "",
                    "error": f"{type(exc).__name__}: {exc}"}
        # 恒定三键形状（与 ExtCommandRunDto 对齐——空值显式入列）
        if isinstance(res, str):
            return {"status": "ok", "text": res, "error": ""}
        if isinstance(res, dict):
            out = {"status": "ok", "text": "", "error": ""}
            for k in ("status", "text", "error"):
                if k in res:
                    out[k] = res[k]
            return out
        return {"status": "ok", "text": str(res), "error": ""}

    def mcp_status(self) -> dict:
        """MCP 状态（阶段 5 · T5.2）：服务/工具/权限声明/连接统计。"""
        cfgs = list(getattr(self, "_mcp_cfgs", None) or [])
        pool = getattr(self, "_mcp_pool", None)
        stats = getattr(pool, "stats", {}) if pool is not None else {}
        by_server: dict = {}
        tools_reg = self.tools if hasattr(self.tools, "list") else None
        for t in (tools_reg.list() if tools_reg else []):
            if getattr(t, "is_mcp", False):
                try:
                    perm = t.permission()
                except Exception:
                    perm = {}
                by_server.setdefault(getattr(t, "_server", ""), []).append(
                    {"name": t.name(), "permissions": perm})
        servers = []
        for c in cfgs:
            servers.append({
                "name": c.name,
                "command": c.command,
                "args": list(c.args or []),
                "tools": sorted(by_server.get(c.name, []),
                                key=lambda x: x["name"]),
                "stats": dict(stats.get(c.name)
                              or {"connections": 0, "calls": 0}),
            })
        return {"enabled": bool(cfgs), "servers": servers}
