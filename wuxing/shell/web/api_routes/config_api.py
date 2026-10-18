"""配置 schema/读写 + 工作区设置路由（Q1：自 api.py register_api 逐字迁移）。"""
from wuxing.config_contract import (
    ConfigConflict,
    ConfigError,
    config_revision,
    describe_config,
    effective_config,
    write_config,
)
from wuxing.shell.web.server import error_response, json_response

from .base import _guard


def register(server, ctx) -> None:
    manager = ctx.manager

    @_guard
    def h_config_schema(req):
        return json_response({"fields": describe_config()})

    @_guard
    def h_workspace_config(req):
        ws = manager.get_workspace(req.params["ws"])
        eff = effective_config(ws["path"])
        return json_response({"workspace": ws,
                              "values": eff["values"],
                              "sources": eff["sources"]})

    @_guard
    def h_global_config(req):
        """用户级 + 默认（无打开工作区时的设置中心数据源）。

        revision（R3-1/D4）：用户层配置文件原文 sha1——写回时携带做冲突检测。
        """
        eff = effective_config(None)
        return json_response({"values": eff["values"],
                              "sources": eff["sources"],
                              "revision": config_revision("user")})

    @_guard
    def h_config_write(req):
        body = req.json() or {}
        scope = str(req.query.get("scope") or "workspace")
        values = body.get("values") or {}
        replace = body.get("replace") or []
        workdir = None
        ws_id = req.query.get("ws")
        if scope == "workspace":
            if not ws_id:
                return error_response(422, "invalid", "工作区级写入需要 ws 参数")
            workdir = manager.get_workspace(ws_id)["path"]
        rev = body.get("revision")
        try:
            out = write_config(scope, values, workdir=workdir,
                               replace_keys=replace,
                               revision=rev if isinstance(rev, str) else None)
        except ConfigConflict as exc:
            return error_response(
                409, "config/conflict",
                f"{exc}（当前 revision: {exc.current_revision or '空'}）")
        except ConfigError as exc:
            return error_response(422, "invalid", str(exc))
        if scope == "user":
            manager.reload_engines()
        else:
            manager.reload_engines(ws_id)
        return json_response(out)

    @_guard
    def h_ws_settings(req):
        ws = manager.get_workspace(req.params["ws"])
        body = req.json() or {}
        if "auto_confirm" in body:
            ws = manager.set_auto_confirm(ws["id"], bool(body["auto_confirm"]))
        return json_response(ws)

    server.add_route("GET", r"^/api/v1/config/schema$", h_config_schema)
    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/config$",
        h_workspace_config)
    server.add_route("GET", r"^/api/v1/config$", h_global_config)
    server.add_route("PUT", r"^/api/v1/config$", h_config_write)
    server.add_route(
        "PUT", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/settings$",
        h_ws_settings)
