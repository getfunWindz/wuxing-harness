"""装配预设/会话绑定/扩展命令路由（Q1：自 api.py 逐字迁移）。"""
from wuxing.shell.web.server import error_response, json_response

from .base import _guard


def register(server, ctx) -> None:
    manager = ctx.manager

    @_guard
    def h_presets(req):
        """E2-4/E2-UI：装配预设清单（组合树 + 解析态 chain/hash/error）。"""
        ws = manager.get_workspace(req.params["ws"])
        from wuxing import presets
        return json_response({"presets": presets.list_with_state(ws["path"])})

    @_guard
    def h_session_preset_get(req):
        """E2-4：会话装配绑定读取（空 = 跟随默认）。"""
        ws = manager.get_workspace(req.params["ws"])
        from wuxing import presets
        session = str(req.query.get("session") or "")
        name = str(presets.load_session(ws["path"]).get(session) or "")
        return json_response({"session": session, "name": name})

    @_guard
    def h_session_preset_put(req):
        """E2-4：会话装配绑定写入（name 空 = 清除；未知预设 422）。"""
        ws = manager.get_workspace(req.params["ws"])
        from wuxing import presets
        body = req.json() or {}
        session = str(body.get("session") or "")
        name = str(body.get("name") or "")
        if name:
            known = {p["name"] for p in presets.list_presets(ws["path"])}
            if name not in known:
                return error_response(422, "invalid", f"未知预设：{name}")
        presets.save_session(ws["path"], session, name)
        manager.reload_engines(req.params["ws"])
        return json_response({"session": session, "name": name})

    @_guard
    def h_ext_commands(req):
        """E2-3：扩展命令清单（命令面板/CLI）。"""
        engine = manager.engine_for(req.params["ws"])
        return json_response({"commands": engine.list_commands()})

    @_guard
    def h_ext_command_run(req):
        """E2-3：执行扩展命令（args 对象；未知命令 404）。"""
        body = req.json() or {}
        args = body.get("args") or {}
        if not isinstance(args, dict):
            return error_response(422, "invalid", "args 需要对象")
        engine = manager.engine_for(req.params["ws"])
        try:
            res = engine.run_command(req.params["command"], args)
        except KeyError as exc:
            return error_response(404, "not-found", str(exc))
        return json_response(res)

    server.add_route(
        "GET",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/extensions/commands$",
        h_ext_commands)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/extensions/commands/(?P<command>[a-z][a-z0-9-]*)$",
        h_ext_command_run)
    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/presets$", h_presets)
    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/session-preset$",
        h_session_preset_get)
    server.add_route(
        "PUT", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/session-preset$",
        h_session_preset_put)
