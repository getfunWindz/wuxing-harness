"""系统对话框桥路由（Q1：自 api.py register_api 逐字迁移）。"""
from wuxing.shell.web.server import error_response, json_response

from .base import _guard


def register(server, ctx) -> None:
    dialog_runner = ctx.dialog_runner

    @_guard
    def h_dialog_pick(req):
        """R1-1/R2-1：系统原生对话框桥（file / files / directory）→ 绝对路径。"""
        body = req.json() or {}
        kind = str(body.get("kind") or "file")
        try:
            paths = list(dialog_runner(kind))
        except ValueError as exc:
            return error_response(422, "invalid", str(exc))
        except RuntimeError as exc:
            return error_response(503, "unavailable", str(exc))
        return json_response({"paths": paths})

    server.add_route("POST", r"^/api/v1/dialog/pick$", h_dialog_pick)
