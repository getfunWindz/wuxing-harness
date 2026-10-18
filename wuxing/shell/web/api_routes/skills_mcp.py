"""技能（管理面 + 工作区级）与 MCP 路由（Q1：自 api.py 逐字迁移）。"""
from wuxing.shell.web.server import error_response, json_response

from .base import _guard


def register(server, ctx) -> None:
    manager = ctx.manager

    @_guard
    def h_skills(req):
        ws = manager.get_workspace(req.params["ws"])
        return json_response({"skills": manager.skills(ws["id"])})

    # ---- 管理面（阶段 5 · T5.1/T5.2） ----

    @_guard
    def h_skills_index(req):
        return json_response({"skills": manager.skills_index()})

    @_guard
    def h_skill_detail(req):
        detail = manager.skill_detail(req.params["name"])
        if detail is None:
            return error_response(404, "not_found", "技能不存在")
        return json_response(detail)

    @_guard
    def h_skill_install(req):
        body = req.json() or {}
        return json_response(manager.skill_install(
            body.get("name", ""), body.get("description", ""),
            body.get("content", ""), body.get("scripts") or None))

    @_guard
    def h_skill_remove(req):
        return json_response(manager.skill_remove(req.params["name"]))

    @_guard
    def h_skill_enabled(req):
        body = req.json() or {}
        if "enabled" not in body:
            return error_response(422, "invalid", "enabled 必填")
        return json_response(manager.skill_set_enabled(
            req.params["name"], bool(body.get("enabled"))))

    @_guard
    def h_skill_discover(req):
        body = req.json() or {}
        out = manager.skill_discover(
            body.get("goal", ""), body.get("constraints", ""),
            int(body.get("max_results") or 5))
        out.setdefault("error", "")  # 契约键恒在（P2-M5）
        return json_response(out)

    @_guard
    def h_mcp_status(req):
        return json_response(manager.mcp_status())

    @_guard
    def h_mcp_reload(req):
        return json_response({"ok": True, "reloaded": manager.mcp_reload()})

    server.add_route("GET", r"^/api/v1/skills$", h_skills_index)
    server.add_route("GET", r"^/api/v1/skills/(?P<name>[^/]+)$", h_skill_detail)
    server.add_route("POST", r"^/api/v1/skills/install$", h_skill_install)
    server.add_route("DELETE", r"^/api/v1/skills/(?P<name>[^/]+)$", h_skill_remove)
    server.add_route("PATCH", r"^/api/v1/skills/(?P<name>[^/]+)$", h_skill_enabled)
    server.add_route("POST", r"^/api/v1/skills/discover$", h_skill_discover)
    server.add_route("GET", r"^/api/v1/mcp$", h_mcp_status)
    server.add_route("POST", r"^/api/v1/mcp/reload$", h_mcp_reload)
    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/skills$", h_skills)
