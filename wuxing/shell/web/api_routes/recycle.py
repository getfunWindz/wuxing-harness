"""回收站 + 工作区/会话归档路由（Q1：自 api.py register_api 逐字迁移）。"""
import logging
import pathlib
import shutil

from wuxing.shell.web.manager import NotFoundError
from wuxing.shell.web.server import error_response, json_response

from .base import _guard, _session_path, _state_arg

logger = logging.getLogger(__name__)


def register(server, ctx) -> None:
    manager = ctx.manager
    recycle = ctx.recycle

    @_guard
    def h_ws_archive(req):
        ws = manager.get_workspace(req.params["ws"])
        state = _state_arg(req)
        if not state:
            return error_response(422, "invalid", "state 必须为 archived/trashed")
        manager.close_workspace(ws["id"])   # 忙 → BusyError 409（不产生记录）
        entry = recycle.add(kind="workspace", state=state,
                            name=ws["name"], path=ws["path"],
                            folder=ws.get("folder") or "")
        return json_response(entry)

    @_guard
    def h_session_archive(req):
        ws = manager.get_workspace(req.params["ws"])
        name = req.params.get("name", "")
        src = _session_path(ws, name)
        if src is None or not src.is_file():
            return error_response(404, "not_found", f"会话不存在：{name}")
        state = _state_arg(req)
        if not state:
            return error_response(422, "invalid", "state 必须为 archived/trashed")
        entry = recycle.add(kind="session", state=state, name=name,
                            path=str(src), ws_path=ws["path"])
        return json_response(entry)

    @_guard
    def h_recycle_list(req):
        return json_response({"entries": recycle.list()})

    @_guard
    def h_recycle_restore(req):
        e = recycle.find(req.params["eid"])
        if e is None:
            return error_response(404, "not_found", "回收站记录不存在")
        if e["kind"] == "workspace":
            # 恢复身份：名称 + 文件夹归属（归档条目里的容器状态须完整回填——
            # 真实应用复现：不回填会导致自定义名退化为目录名、归属丢失）
            ws = manager.open_workspace(e["path"], name=e.get("name") or None)
            folder = e.get("folder") or ""
            if folder:
                try:
                    manager.set_workspace_folder(ws["id"], folder)
                except NotFoundError as exc:
                    logger.debug("文件夹已删除，回退未分组（不阻断）：%s", exc)
        recycle.remove(e["id"])
        return json_response({"ok": True, "kind": e["kind"]})

    @_guard
    def h_recycle_purge(req):
        if str(req.query.get("purge") or "").lower() not in ("1", "true", "yes"):
            return error_response(422, "invalid", "彻底删除需要显式 purge=true")
        e = recycle.find(req.params["eid"])
        if e is None:
            return error_response(404, "not_found", "回收站记录不存在")
        engine = str(req.query.get("engine") or "").lower() in ("1", "true", "yes")
        if e["kind"] == "session":
            src = pathlib.Path(e["path"])
            base = (pathlib.Path(e["ws_path"]) / ".wuxing").resolve()
            if src.resolve().is_relative_to(base) and src.is_file():
                src.unlink()          # 会话文件属引擎数据，可清；用户产物不碰
        elif e["kind"] == "task":
            manager.purge_history(str(e["path"]))   # 壳侧任务记录行移除
        elif e["kind"] == "workspace" and engine:
            ws_root = pathlib.Path(e["path"]).resolve()
            data_dir = (ws_root / ".wuxing").resolve()
            if data_dir.is_relative_to(ws_root) and data_dir.is_dir():
                shutil.rmtree(data_dir)   # 显式 engine=true 才清引擎数据
        recycle.remove(e["id"])
        return json_response({"ok": True, "kind": e["kind"]})

    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/archive$",
        h_ws_archive)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/sessions/(?P<name>[^/]+)/archive$",
        h_session_archive)
    server.add_route("GET", r"^/api/v1/recycle$", h_recycle_list)
    server.add_route(
        "POST", r"^/api/v1/recycle/(?P<eid>[0-9a-zA-Z]+)/restore$",
        h_recycle_restore)
    server.add_route(
        "DELETE", r"^/api/v1/recycle/(?P<eid>[0-9a-zA-Z]+)$",
        h_recycle_purge)
