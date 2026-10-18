"""工具注册表（P2 将扩展 MCP 桥；本层对执行单元无差别）。"""
from wuxing.protocols import Tool


def _type_ok(t: str, v) -> bool:
    """JSON Schema 基本类型检查（L2-2 FC 层1——约束解码的 harness 侧实现）。"""
    return {
        "string": lambda x: isinstance(x, str),
        "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
        "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
        "boolean": lambda x: isinstance(x, bool),
        "object": lambda x: isinstance(x, dict),
        "array": lambda x: isinstance(x, list),
    }.get(t, lambda x: True)(v)


def whitelist_accepts(name: str, whitelist: tuple, is_mcp: bool = False) -> bool:
    """白名单匹配（A5 修复，2026-09-07）：精确名 + MCP 前缀语义。

    MCP 工具已受双闸（显式配置引入 + permissions 声明）；域白名单作为第三闸
    对 MCP 按前缀放行：
      - "mcp:*"       → 全部 MCP 工具（仅 is_mcp 标记工具——不污染内置名）
      - "mcp:{server}" → 该 server 的全部工具（R3-2：mcp__{server}__{tool} 命名契约）
    非 MCP 工具：仅精确名匹配（mcp: 条目对其无效果）。
    """
    if name in whitelist:
        return True
    if not is_mcp:
        return False
    for entry in whitelist:
        if entry == "mcp:*":
            return True
        if entry.startswith("mcp:") and not entry.endswith("*"):
            server = entry[4:]
            if server and name.startswith(f"mcp__{server}__"):
                return True
    return False


def validate_args(schema: dict, kwargs: dict) -> list:
    """input_schema → 错误列表（L2-2：required 缺失 / 类型不符——调用前拦截）。

    返回空列表 = 合法。required 语义：键缺失或值 None（空串放行——文本协议
    常见 k= 空值不误伤）。
    """
    errs = []
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    for req in schema.get("required", []) or []:
        if req not in kwargs or kwargs.get(req) is None:
            errs.append(f"missing required: {req}")
    for k, v in kwargs.items():
        if k not in props:
            continue
        t = props[k].get("type")
        if t and not _type_ok(t, v):
            errs.append(f"{k}: 期望 {t}，实际 {type(v).__name__}")
    return errs


class ToolRegistry:
    def __init__(self, tools: list):
        self._tools = {t.name(): t for t in tools}
        self._guard = None   # (name, kwargs) -> bool；False 拦截（P5 Task 4 用）
        self._ext_interceptor = None  # E2-2：扩展 tool_call 干预（改参/拦截）
        self._ext_domains = {}  # E0-A：域 → 扩展工具名集（运行期有效白名单）

    def register(self, tool):
        """追加工具（3c：Engine 装配 delegate 等后置注入工具）。"""
        self._tools[tool.name()] = tool

    def register_extension(self, tool, domains) -> bool:
        """E0-A：扩展工具注册 + 域可见性登记（不改域定义本体）。

        名字冲突 → False（调用方登记可见——拒绝后者；设计 §2.1）。
        """
        name = tool.name()
        if name in self._tools:
            return False
        self._tools[name] = tool
        for d in (domains or ()):
            self._ext_domains.setdefault(str(d), set()).add(name)
        return True

    def set_guard(self, guard):
        self._guard = guard

    def set_ext_interceptor(self, fn):
        """E2-2：扩展 tool_call 干预器（fn(name, kwargs) → None|{"args"}|{"deny"}）。"""
        self._ext_interceptor = fn

    def get(self, name: str) -> Tool:
        return self._tools.get(name)

    def list(self) -> list:
        return list(self._tools.values())

    def filter(self, whitelist: tuple, domain_id: str | None = None) -> list:
        """白名单过滤（A5：MCP 工具按 mcp: 前缀语义匹配——is_mcp 标记才参与
        前缀匹配，内置工具仅精确名——MCP 不再被域白名单死闸）。

        E0-A：提供 domain_id 时合并扩展工具域声明（有效白名单——不改域定义本体）。
        """
        extra = self._ext_domains.get(domain_id, ()) if domain_id else ()
        out = []
        for t in self._tools.values():
            if t.name() in whitelist or t.name() in extra:
                out.append(t)
                continue
            if getattr(t, "is_mcp", False) and whitelist_accepts(
                    t.name(), whitelist, is_mcp=True):
                out.append(t)
        return out

    def execute(self, name: str, **kwargs):
        """统一执行：守卫前置 → 工具执行；全部返回结构化 ToolResult。"""
        from wuxing.protocols import ToolResult
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(status="error", tool_name=name, error=f"unknown tool: {name}")
        # E3-2（P0）：扩展干预 v2（allow/deny/ask + updated_input）——在守卫之前
        # （守卫校验最终参数——钩子不得绕过白名单/守卫/沙箱）
        if self._ext_interceptor is not None:
            try:
                verdict = self._ext_interceptor(name, kwargs)
            except Exception:
                verdict = None
            if isinstance(verdict, dict):
                decision = str(verdict.get("decision") or "")
                if decision == "deny" or verdict.get("deny"):
                    reason = (verdict.get("reason") or verdict.get("deny") or "")
                    return ToolResult(status="error", tool_name=name,
                                      error=f"扩展拦截：{reason}")
                if decision == "ask":
                    reason = str(verdict.get("reason") or "")
                    return ToolResult(
                        status="error", tool_name=name,
                        error=f"扩展询问：{reason}（需用户确认后重试）")
                new_args = verdict.get("updated_input") or verdict.get("args")
                if isinstance(new_args, dict):
                    kwargs = new_args
        if self._guard:
            verdict = self._guard(name, kwargs)
            if verdict is not True:
                # guard 可返回 False（通用拦截）或 str（拦截原因——透出给事件/界面）
                err = verdict if isinstance(verdict, str) else "guard: blocked by policy"
                return ToolResult(status="blocked", tool_name=name, error=err)
        # P3 T2：权限声明制校验（最小权限——未声明能力的工具默认拒绝）
        perm = getattr(tool, "permission", None)
        perm = perm() if callable(perm) else {}
        if not any(perm.values()):
            return ToolResult(status="blocked", tool_name=name,
                              error="permission: tool has no declared permissions")
        # L2-2（FC 层1 约束）：调用前 schema 校验——参数错在源头拦截，
        # 错误回填给模型（[tool:error] 可见——不吞错，模型下一轮可修正）
        try:
            schema = tool.input_schema()
        except Exception:
            schema = {}
        errs = validate_args(schema, kwargs)
        if errs:
            return ToolResult(status="error", tool_name=name,
                              error="param: " + "; ".join(errs))
        try:
            if getattr(tool, "reentrant", False):
                result = tool.execute(**kwargs)
            else:
                # 分级放行（2026-09-11 用户裁决）：软缓速/硬阻止/滞回
                from wuxing.concurrency import get_limiter
                limiter = get_limiter()
                limiter.acquire()
                try:
                    result = tool.execute(**kwargs)
                finally:
                    limiter.release()
        except Exception as e:  # 冒烟根因3：工具异常不挂引擎（结构化兜底）
            return ToolResult(status="error", tool_name=name,
                              error=f"{type(e).__name__}: {e}")
        if isinstance(result, ToolResult):
            result.tool_name = result.tool_name or name
            return result
        # 向后兼容：非 ToolResult（跳过结构化改造的工具）→ 包装
        return ToolResult(status="ok", content=result, tool_name=name)
