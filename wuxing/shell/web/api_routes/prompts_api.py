"""域提示词 查看/保存（重大优化清单 #3）——设置「域提示词」分区运维面。

存档 `wuxing/domain_prompts.py`（两层本机文件，逐字段覆盖）。GET 返回各层原值/
生效值/内置默认 + problems；POST 按 scope 逐字段写入（空串=清除回退；超限/未知域 → 422）。
"""
from wuxing import domain_prompts
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
        entries, problems = domain_prompts.all_effective(ws_root)
        return {"entries": entries, "problems": problems}

    @_guard
    def h_prompts_get(req):
        ws_id = str(req.query.get("ws") or "").strip()
        return json_response(_payload(_ws_root(ws_id)))

    @_guard
    def h_prompts_save(req):
        body = req.json() or {}
        scope = str(body.get("scope") or "user")
        if scope not in ("user", "workspace"):
            return error_response(422, "invalid", "scope 必须为 user 或 workspace")
        ws_id = str(body.get("ws") or req.query.get("ws") or "").strip()
        ws_root = _ws_root(ws_id)
        if scope == "workspace" and ws_root is None:
            return error_response(422, "invalid", "工作区级写入需要有效 ws")
        _, errors = domain_prompts.save_scope(scope, ws_root,
                                              body.get("values") or {})
        if errors:
            return error_response(422, "invalid", "；".join(errors))
        return json_response(_payload(ws_root))

    server.add_route("GET", r"^/api/v1/prompts/domains$", h_prompts_get)
    server.add_route("POST", r"^/api/v1/prompts/domains$", h_prompts_save)
