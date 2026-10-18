"""api_routes 共享基础：注册上下文 + 跨组工具（Q1 拆分，自 api.py 逐字迁移）。"""
import pathlib
from dataclasses import dataclass

from wuxing.shell.web.manager import BusyError, ManagerError, NotFoundError
from wuxing.shell.web.server import error_response


@dataclass
class ApiContext:
    """注册面共享依赖（handler 经局部别名闭包访问——保持原 api.py 形式）。"""
    manager: object
    recycle: object
    dialog_runner: object
    title_runner: object

    @property
    def hub(self):
        return self.manager.hub


def _guard(fn):
    """管理器异常 → HTTP 契约（not_found 404 / busy 409 / invalid 422）。"""
    def wrapper(req):
        try:
            return fn(req)
        except NotFoundError as exc:
            return error_response(404, "not_found", str(exc))
        except BusyError as exc:
            return error_response(409, "busy", str(exc))
        except ValueError as exc:
            return error_response(422, "invalid", str(exc))
        except ManagerError as exc:
            return error_response(500, exc.code, str(exc))
    return wrapper


# 内部 JSONL（会话列表/搜索等场景排除——不是用户会话）
_INTERNAL_JSONL = {"provenance.jsonl", "trace.jsonl", "unit-bindings.jsonl",
                   "context-edits.jsonl", "branches.jsonl",
                   "tickets.jsonl"}  # 2026-09-27 审查：票据文件曾被列为幽灵会话


def _session_path(ws, name: str):
    raw = str(name or "").strip()
    if raw == "" or raw in _INTERNAL_JSONL:
        return None
    if "/" in raw or "\\" in raw:
        return None
    if not raw.endswith(".jsonl"):
        raw = raw + ".jsonl"
    base = (pathlib.Path(ws["path"]) / ".wuxing").resolve()
    target = (base / raw).resolve()
    if not target.is_relative_to(base):
        return None
    return target


def _state_arg(req) -> str:
    body = {} if req.method == "GET" else (req.json() or {})
    state = str(body.get("state") or "archived")
    return state if state in ("archived", "trashed") else ""
