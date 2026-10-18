"""任务提交/确认/快照/产物/回滚/归档路由（Q1：自 api.py register_api 逐字迁移）。"""
import mimetypes
import pathlib

from wuxing.shell.web.server import Response, error_response, json_response

from .base import _guard, _state_arg


def register(server, ctx) -> None:
    manager = ctx.manager
    recycle = ctx.recycle

    @_guard
    def h_submit(req):
        body = req.json()
        refs = body.get("references") or None
        if refs is not None and not isinstance(refs, list):
            return error_response(422, "invalid", "references 需要字符串列表")
        # 碎片会话后半程（2026-09-22）：碎片视图内提交携带绑定身份（空 = 主会话提交）
        unit_id = str(body.get("unit") or "").strip()[:200]
        # 二期批 1：显式闸覆盖（仅 "no_map"——无地图执行；未知值早报）
        override = str(body.get("override") or "").strip()
        if override not in ("", "no_map"):
            return error_response(422, "invalid", f"未知 override：{override!r}")
        run_id = manager.submit(req.params["ws"], body.get("text", ""),
                                references=refs,
                                session=str(body.get("session") or "") or None,
                                unit=unit_id or None,
                                override=override or None,
                                claim_override=bool(body.get("claim_override")),
                                isolate_run=bool(body.get("isolate_run")))
        rec = manager.get_run(run_id)
        return json_response({"run_id": run_id,
                              "workspace_id": req.params["ws"],
                              "session": rec.get("session", ""),
                              "unit": unit_id}, status=202)

    @_guard
    def h_confirm(req):
        body = req.json()
        rec = manager.confirm(req.params["run"], body.get("items") or [],
                              reason=str(body.get("reason", "")))
        return json_response(rec)

    @_guard
    def h_answer(req):
        """E2-5（A10）：答复提问（挂起单元续跑）。"""
        body = req.json()
        return json_response(manager.answer(
            req.params["run"],
            str(body.get("unit_id", "")),
            str(body.get("question_id", "")),
            str(body.get("answer", "")),
            source=str(body.get("source", "text")),
            reason=str(body.get("reason", ""))))

    @_guard
    def h_resume(req):
        return json_response(manager.resume(req.params["run"]))

    @_guard
    def h_resume_ws(req):
        return json_response(manager.resume_workspace(req.params["ws"]))

    @_guard
    def h_abandon_ws(req):
        return json_response(manager.abandon_workspace(req.params["ws"]))

    @_guard
    def h_cancel(req):
        return json_response(manager.cancel(req.params["run"]))

    @_guard
    def h_snapshot(req):
        return json_response(manager.snapshot(req.params["ws"]))

    @_guard
    def h_artifact(req):
        ws = manager.get_workspace(req.params["ws"])
        root = pathlib.Path(ws["path"]).resolve()
        target = (root / req.params.get("path", "")).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return error_response(404, "not_found",
                                  f"产物不存在：{req.params.get('path', '')}")
        ctype = mimetypes.guess_type(str(target))[0] or \
            "application/octet-stream"
        if ctype.startswith("text/"):
            ctype += "; charset=utf-8"
        return Response(200, target.read_bytes(), ctype)

    @_guard
    def h_task_history(req):
        ws = manager.get_workspace(req.params["ws"])
        try:
            limit = int(req.query.get("limit") or 50)
        except (TypeError, ValueError):
            return error_response(422, "invalid", "limit 必须为整数")
        hidden = recycle.hidden_run_ids(ws["path"])
        hist = [h for h in manager.history(ws["id"], limit=limit)
                if str(h.get("run_id")) not in hidden]
        return json_response({"history": hist})


    @_guard
    def h_rollback(req):
        manager.get_workspace(req.params["ws"])
        body = req.json() or {}
        return json_response(manager.rollback(
            req.params["run"],
            delete_artifacts=bool(body.get("delete_artifacts", False))))

    @_guard
    def h_task_archive(req):
        ws = manager.get_workspace(req.params["ws"])
        run_id = req.params["run"]
        rec = manager.get_run(run_id)
        state = _state_arg(req)
        if not state:
            return error_response(422, "invalid", "state 必须为 archived/trashed")
        entry = recycle.add(kind="task", state=state,
                            name=str(rec.get("task_text") or run_id)[:60],
                            path=run_id, ws_path=ws["path"])
        return json_response(entry)

    @_guard
    def h_worktree_review(req):
        """E3-1/R5（T5）：隔离 run 变更视图（Review 面板数据源）。"""
        return json_response(manager.worktree_review(req.params["run"]))

    @_guard
    def h_worktree_apply(req):
        """E3-1/R5（T5）：应用变更到主检出（显式；冲突 422 可见）。"""
        return json_response(manager.worktree_apply(req.params["run"]))

    @_guard
    def h_worktree_discard(req):
        """E3-1/R5（T5）：丢弃 worktree（主检出零改动）。"""
        return json_response(manager.worktree_discard(req.params["run"]))

    server.add_route("POST",
                     r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks$",
                     h_submit)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)"
        r"/answer$", h_answer)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)"
        r"/confirm$", h_confirm)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)"
        r"/resume$", h_resume)
    server.add_route(
        "POST", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/resume$", h_resume_ws)
    server.add_route(
        "POST", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/abandon$", h_abandon_ws)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)"
        r"/cancel$", h_cancel)
    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/snapshot$", h_snapshot)
    server.add_route(
        "GET",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/artifacts/(?P<path>.+)$",
        h_artifact)
    server.add_route(
        "GET",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/history$",
        h_task_history)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)"
        r"/rollback$", h_rollback)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)"
        r"/archive$", h_task_archive)
    server.add_route(
        "GET",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)"
        r"/worktree$", h_worktree_review)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)"
        r"/worktree/apply$", h_worktree_apply)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)"
        r"/worktree/discard$", h_worktree_discard)
