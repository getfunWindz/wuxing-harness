"""工作区/文件夹/目录浏览路由（Q1：自 api.py register_api 逐字迁移）。"""
import os
import pathlib

from wuxing.shell.web.server import error_response, json_response

from .base import _guard


def register(server, ctx) -> None:
    manager = ctx.manager

    @_guard
    def h_list(req):
        return json_response({"workspaces": manager.list_workspaces(),
                              "folders": manager.list_folders()})

    @_guard
    def h_open(req):
        body = req.json()
        ws = manager.open_workspace(
            body.get("path", ""),
            auto_confirm=bool(body.get("auto_confirm", False)),
            name=body.get("name"))
        return json_response(ws)

    @_guard
    def h_fs_list(req):
        """目录浏览（新建工作区·浏览入口）——仅列子目录（隐藏 dot 目录）。"""
        raw = (req.query.get("path") or "").strip()
        if not raw:
            if os.name == "nt":
                dirs = [{"name": f"{d}:\\", "path": f"{d}:\\"}
                        for d in "CDEFGH"
                        if pathlib.Path(f"{d}:\\").exists()]
            else:
                dirs = [{"name": "/", "path": "/"}]
            return json_response({"path": "", "parent": None, "dirs": dirs})
        p = pathlib.Path(raw).expanduser()
        if not p.is_dir():
            return error_response(404, "not_found", f"目录不存在：{raw}")
        p = p.resolve()
        dirs = []
        try:
            for child in sorted(p.iterdir(), key=lambda x: x.name.lower()):
                if child.name.startswith("."):
                    continue
                if child.is_dir():
                    dirs.append({"name": child.name, "path": str(child)})
                    if len(dirs) >= 500:
                        break
        except OSError as exc:
            return error_response(403, "denied", f"无法读取目录：{exc}")
        parent = str(p.parent) if p.parent != p else None
        return json_response({"path": str(p), "parent": parent, "dirs": dirs})

    @_guard
    def h_close(req):
        manager.close_workspace(req.params["ws"])
        return json_response({"ok": True})

    # ---- 工作区文件夹（验收迭代 3 · 4b） ----

    @_guard
    def h_folder_create(req):
        body = req.json()
        return json_response(manager.create_folder(body.get("name", "")))

    @_guard
    def h_folder_update(req):
        body = req.json()
        return json_response(manager.update_folder(
            req.params["fid"], name=body.get("name"),
            collapsed=body.get("collapsed")))

    @_guard
    def h_folder_delete(req):
        return json_response(manager.delete_folder(req.params["fid"]))

    @_guard
    def h_ws_folder(req):
        body = req.json()
        ws = manager.set_workspace_folder(req.params["ws"], body.get("folder"))
        return json_response({"ok": True, "workspace": ws})

    server.add_route("GET", r"^/api/v1/workspaces$", h_list)
    server.add_route("POST", r"^/api/v1/workspaces$", h_open)
    server.add_route("POST", r"^/api/v1/folders$", h_folder_create)
    server.add_route("PATCH", r"^/api/v1/folders/(?P<fid>[0-9a-f]+)$",
                     h_folder_update)
    server.add_route("DELETE", r"^/api/v1/folders/(?P<fid>[0-9a-f]+)$",
                     h_folder_delete)
    server.add_route("PUT",
                     r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/folder$",
                     h_ws_folder)
    server.add_route("DELETE",
                     r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)$", h_close)
    server.add_route("GET", r"^/api/v1/fs/list$", h_fs_list)
