"""REST + SSE 接线（壳 P1 · B4）——快照-流握手 + 确认回路。

设计 §4.1/§4.2：REST 命令面（`/api/v1/*`）；SSE 事件流
（hello → 重放 → 实时；心跳注释行）；快照含 `last_seq`（高水位）——
客户端以 `since` 无缝续流；缓冲缺口 → `resync_required`（重拉快照再订阅）。
路由实现按域分组在 `api_routes/`（Q1）；本模块只做默认值装配与注册。
"""
import pathlib

from wuxing.shell.web import native_dialog, session_titles
from wuxing.shell.web.api_routes import browser_api as _browser
from wuxing.shell.web.api_routes import config_api as _config
from wuxing.shell.web.api_routes import context as _context
from wuxing.shell.web.api_routes import dialog as _dialog
from wuxing.shell.web.api_routes import extensions as _extensions
from wuxing.shell.web.api_routes import interaction_api as _interaction
from wuxing.shell.web.api_routes import observe as _observe
from wuxing.shell.web.api_routes import prompts_api as _prompts
from wuxing.shell.web.api_routes import providers as _providers
from wuxing.shell.web.api_routes import recycle as _recycle
from wuxing.shell.web.api_routes import sessions as _sessions
from wuxing.shell.web.api_routes import skills_mcp as _skills_mcp
from wuxing.shell.web.api_routes import stream as _stream
from wuxing.shell.web.api_routes import tasks as _tasks
from wuxing.shell.web.api_routes import theroad as _theroad
from wuxing.shell.web.api_routes import workspaces as _workspaces
from wuxing.shell.web.api_routes.base import ApiContext
from wuxing.shell.web.state import RecycleStore


def register_api(server, manager, recycle=None, dialog_runner=None,
                 title_runner=None) -> None:
    """把 REST/SSE 端点注册到 ShellServer（引擎/管理器/回收站均为构造注入）。

    dialog_runner：系统对话框桥（kind → 路径列表）；测试/夹具可注入桩。
    title_runner：会话标题生成（会话文件路径 → 标题）；测试/夹具可注入桩。
    """
    recycle = recycle if recycle is not None else RecycleStore()
    if dialog_runner is None:
        def _default_dialog(kind):
            return native_dialog.pick(kind=kind, title="WUXING")
        dialog_runner = _default_dialog
    if title_runner is None:
        def _default_title(path):
            """默认：工作区引擎的规划域模型总结首轮（失败/无凭据 → 空串）。"""
            try:
                target = pathlib.Path(path).resolve()
                for ws in manager.list_workspaces():
                    wd = pathlib.Path(ws["path"]).resolve()
                    if target.is_relative_to(wd):
                        engine = manager.engine_for(ws["id"])
                        return session_titles.generate_title(target,
                                                             engine.llm_for("plan"))
            except Exception:
                # 标题生成失败 → 空串（后台标题补齐：失败静默降级）
                return ""
            return ""
        title_runner = _default_title

    ctx = ApiContext(manager=manager, recycle=recycle,
                     dialog_runner=dialog_runner, title_runner=title_runner)
    _dialog.register(server, ctx)
    _workspaces.register(server, ctx)
    _tasks.register(server, ctx)
    _sessions.register(server, ctx)
    _context.register(server, ctx)
    _theroad.register(server, ctx)
    _extensions.register(server, ctx)
    _skills_mcp.register(server, ctx)
    _config.register(server, ctx)
    _providers.register(server, ctx)
    _observe.register(server, ctx)
    _browser.register(server, ctx)
    _prompts.register(server, ctx)
    _interaction.register(server, ctx)
    _recycle.register(server, ctx)
    _stream.register(server, ctx)
