"""THEROAD 路由（地图/票据/发布/重置）+ 会话承接简报（Q1：自 api.py 逐字迁移）。"""
import pathlib

from wuxing.shell.web.server import error_response, json_response

from .base import _INTERNAL_JSONL, _guard


def register(server, ctx) -> None:
    manager = ctx.manager

    @_guard
    def h_tickets(req):
        """二期批 4：实施票据列表（只读——工作区级执行清单）。"""
        ws = manager.get_workspace(req.params["ws"])
        from wuxing import design_state, tickets
        wd = ws["path"]
        st = design_state.load(wd)
        # G8-M3：陈旧认领标记（认领者无活动 run 支撑）
        rows = tickets.annotate_claims(
            tickets.load(wd),
            manager.active_sessions(req.params["ws"]))
        return json_response({"tickets": rows,
                              "spec": str(st.get("spec_slug") or "")})

    @_guard
    def h_tickets_publish(req):
        """二期批 4：用户 quiz 发布（proposed→ready；依赖图校验含环拒绝）。

        审查 F2：ids 区分「缺省（全部 proposed）」与「显式列表（[]=不发布）」；
        显式指定非 proposed 票据 → 422（不静默重置状态机）。
        """
        ws = manager.get_workspace(req.params["ws"])
        body = req.json()
        ids = body.get("ids")
        if ids is not None and not isinstance(ids, list):
            return error_response(422, "invalid", "ids 需要字符串列表")
        from wuxing import tickets
        wd = ws["path"]
        before = {str(t["id"]): str(t.get("status") or "")
                  for t in tickets.load(wd)}
        try:
            ts = tickets.publish(
                wd, None if ids is None else [str(i) for i in ids])
        except ValueError as e:
            return error_response(422, "invalid", str(e))
        for t in ts:  # SSE：仅本状态迁移到 ready 的票据（不广播无变化项）
            if (str(t.get("status")) == "ready"
                    and before.get(str(t["id"])) != "ready"):
                manager.hub.emit("impl_ticket_changed",
                                 workspace_id=req.params["ws"], run_id="",
                                 data={"id": t["id"], "status": t["status"],
                                       "spec": str(t.get("spec") or "")})
        return json_response({"tickets": ts})

    @_guard
    def h_tickets_reset(req):
        """W4.5：用户重置失败票（失败票重跑 + 依赖闭包）→ ready。

        ids 缺省 = 全部 failed/cancelled；非法（未知/running/proposed）→ 422。
        """
        ws = manager.get_workspace(req.params["ws"])
        body = req.json()
        ids = body.get("ids")
        if ids is not None and not isinstance(ids, list):
            return error_response(422, "invalid", "ids 需要字符串列表")
        from wuxing import tickets
        wd = ws["path"]
        before = {str(t["id"]): str(t.get("status") or "")
                  for t in tickets.load(wd)}
        try:
            ts = tickets.reset(
                wd, None if ids is None else [str(i) for i in ids])
        except ValueError as e:
            return error_response(422, "invalid", str(e))
        for t in ts:  # SSE：仅本状态迁移到 ready 的票据（不广播无变化项）
            if (str(t.get("status")) == "ready"
                    and before.get(str(t["id"])) != "ready"):
                manager.hub.emit("impl_ticket_changed",
                                 workspace_id=req.params["ws"], run_id="",
                                 data={"id": t["id"], "status": t["status"],
                                       "spec": str(t.get("spec") or "")})
        return json_response({"tickets": ts})

    @_guard
    def h_map(req):
        """双模式批 3（循迹）：工作区地图只读视图。"""
        ws = manager.get_workspace(req.params["ws"])
        from wuxing import map_doc
        wd = ws["path"]
        d = map_doc.read(wd) or {}
        return json_response({
            "available": bool(d),
            "project": str(d.get("project") or ""),
            "destination": str(d.get("destination") or ""),
            "route": list(d.get("route") or []),
            "decisions": map_doc.parse_decisions(d.get("decisions") or []),
            "fog": list(d.get("fog") or []),
            "out_of_scope": list(d.get("out_of_scope") or []),
            "hash": map_doc.file_hash(map_doc.map_path(wd))})

    @_guard
    def h_handoff_brief(req):
        """双模式批 4：新会话承接简报（确定性拼装——无 LLM）。"""
        ws = manager.get_workspace(req.params["ws"])
        session = (req.query.get("session") or "").strip()
        if not session:
            return error_response(422, "invalid", "需要 session 参数")
        if "/" in session or "\\" in session or session in _INTERNAL_JSONL:
            return error_response(422, "invalid", f"非法会话名：{session}")
        from wuxing.handoff import build_brief
        wd = ws["path"]
        return json_response(build_brief(
            wd, pathlib.Path(wd) / ".wuxing" / session))

    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/map$",
        h_map)
    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tickets$",
        h_tickets)
    server.add_route(
        "POST", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tickets/publish$",
        h_tickets_publish)
    server.add_route(
        "POST", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tickets/reset$",
        h_tickets_reset)
    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/handoff-brief$",
        h_handoff_brief)
