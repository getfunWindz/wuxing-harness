"""统一工具装载器（P2：内置 + MCP 混合装载；执行单元无差别消费）。"""
import asyncio
import logging
from dataclasses import dataclass, field

from wuxing.tools.ask_tool import AskUserTool
from wuxing.tools.base import ToolRegistry
from wuxing.tools.bash_tool import BashTool
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.tools.fs_tools import ReadFileTool, WriteFileTool
from wuxing.tools.mcp_bridge import load_mcp_tools
from wuxing.tools.run_tests_tool import RunTestsTool
from wuxing.tools.search_tools import GlobTool, GrepTool
from wuxing.tools.session_tools import SessionSearchTool
from wuxing.tools.skill_tool import LoadSkillTool
from wuxing.tools.todo_tool import TodoWriteTool

logger = logging.getLogger(__name__)


def merge_mcp_generation(mcp_tools: list, existing_names) -> list:
    """R3-2/M1：MCP 工具注册原子性——冲突即整代回滚（full generation or none）。

    冲突 = 与既有工具重名 或 代内重名；回滚时告警留痕（不静默）。
    """
    names = [t.name() for t in mcp_tools]
    if len(names) != len(set(names)):
        logger.warning("MCP 工具代内重名——整代回滚：%s", sorted(names))
        return []
    clash = sorted(set(existing_names) & set(names))
    if clash:
        logger.warning("MCP 工具与既有工具冲突——整代回滚：%s", clash)
        return []
    return mcp_tools


@dataclass
class ToolLoaderConfig:
    mcp_servers: list = field(default_factory=list)  # [McpServerConfig]

def load_tools(ws, cfg: ToolLoaderConfig = None, skills=None,
                 sandbox_enabled: bool = True,
                 sandbox_mode: str = "native",
                 sandbox_container_template: str = "",
                 bash_shell_path: str = "",
                 bash_timeout_s: float = 120.0,
                 mcp_pool=None,
                 tool_search_enabled: bool = True,
                 tool_search_threshold: int = 20,
                 mcp_always_load=(),
                 web_fetch=None,
                 code_mode=None,
                 browser=None) -> ToolRegistry:
    """统一装载：内置 + MCP 混合，返回 ToolRegistry（守卫挂载点在上层设置）。

    skills：SK 渐进披露——load_skill 工具（碎片级被动调用）随内置装载。
    web_fetch：E2-5 条件装载——WebFetchTool 实例或 None（未启用不注册）。
    mcp_pool：E1 常驻连接池（None=按次连接兜底——测试兼容）。
    E3-3（X6）：MCP 工具超阈值且未豁免 → 延迟（deferred——不进提示词工具表，
    模型经 tool_search 检索）；存在延迟工具时注册 tool_search。
    """
    cfg = cfg or ToolLoaderConfig()
    tools = BUILTIN_TOOLS(ws) + [ReadFileTool(ws), WriteFileTool(ws),
                                 GlobTool(ws), GrepTool(ws),
                                 SessionSearchTool(ws),
                                 TodoWriteTool(),
                                 AskUserTool(),   # E2-5（A10）：挂起式提问
                                 BashTool(ws, timeout=bash_timeout_s,
                                          shell_path=bash_shell_path,
                                          sandbox_enabled=sandbox_enabled,
                                          sandbox_mode=sandbox_mode,
                                          container_template=sandbox_container_template),
                                 RunTestsTool(ws, timeout=bash_timeout_s,
                                              shell_path=bash_shell_path,
                                              sandbox_enabled=sandbox_enabled,
                                              sandbox_mode=sandbox_mode,
                                              container_template=sandbox_container_template),
                                 LoadSkillTool(skills)]
    if web_fetch is not None:
        tools.append(web_fetch)  # E2-5：条件注册（未启用不注册——工具面最小化）
    if code_mode is not None:
        tools.append(code_mode)  # A4：条件注册（未启用不注册——工具面最小化）
    if browser is not None:
        tools += list(browser)  # O2-2：内置浏览器条件注册（未启用不注册）
    deferred_any = False
    if cfg.mcp_servers:
        mcp_tools = asyncio.run(load_mcp_tools(cfg.mcp_servers, pool=mcp_pool))
        mcp_tools = merge_mcp_generation(mcp_tools, [t.name() for t in tools])
        try:
            _threshold = int(tool_search_threshold or 0)
        except (TypeError, ValueError):
            _threshold = 0
        if tool_search_enabled and _threshold > 0 \
                and len(mcp_tools) > _threshold:
            _exempt = {str(x) for x in (mcp_always_load or ())}
            for t in mcp_tools:
                if str(getattr(t, "_server", "")) in _exempt:
                    continue
                t.deferred = True
                deferred_any = True
        tools += mcp_tools
    registry = ToolRegistry(tools)
    if deferred_any:
        from wuxing.tools.tool_search import ToolSearchTool
        registry.register(ToolSearchTool(registry))
    return registry
