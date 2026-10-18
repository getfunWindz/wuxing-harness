"""交互偏好 查看/保存（#2 Phase 1.5）——设置「交互与文案」分区运维面。

存档 `wuxing/interaction_prefs.py`（两层本机文件，逐字段覆盖）。
GET 返回两层原值/生效值/来源/problems；POST 按 scope 逐字段写入
（None=删除回退；非法值/未知字段 → 422）。
"""
from wuxing import interaction_prefs
from wuxing.shell.web.server import error_response, json_response

from .base import _guard


def register(server, ctx) -> None:
    manager = ctx.manager

    def _ws_root(ws_id: str):
        if not ws_id:
            return None
        try:
            return manager.get_workspace(ws_id)["path"]
        except Exception:
            # 未知/已关闭工作区 → None（GET 退化为仅用户层；POST 工作区级由
            # 调用侧 loud 拒绝 422）——可恢复语义，不上抛
            return None

    def _payload(ws_root) -> dict:
        return interaction_prefs.all_effective(ws_root)

    @_guard
    def h_prefs_get(req):
        ws_id = str(req.query.get("ws") or "").strip()
        return json_response(_payload(_ws_root(ws_id)))

    @_guard
    def h_prefs_save(req):
        body = req.json() or {}
        scope = str(body.get("scope") or "user")
        if scope not in ("user", "workspace"):
            return error_response(422, "invalid", "scope 必须为 user 或 workspace")
        ws_id = str(body.get("ws") or req.query.get("ws") or "").strip()
        ws_root = _ws_root(ws_id)
        if scope == "workspace" and ws_root is None:
            return error_response(422, "invalid", "工作区级写入需要有效 ws")
        _, errors = interaction_prefs.save_scope(scope, ws_root,
                                                 body.get("values") or {})
        if errors:
            return error_response(422, "invalid", "；".join(errors))
        return json_response(_payload(ws_root))

    server.add_route("GET", r"^/api/v1/interaction$", h_prefs_get)
    server.add_route("POST", r"^/api/v1/interaction$", h_prefs_save)
