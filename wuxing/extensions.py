"""扩展机制（E0-A 一期）：自定义工具 + 事件钩子。

设计：docs/WUXING_扩展机制设计_2026-09-26.md（用户批准 D1/D2/D3）。
- 目录：~/.wuxing/extensions/*.py（用户级）+ <workdir>/.wuxing/extensions/*.py（项目级）
  + `extension_dirs` 附加目录（相对路径按工作区解析）；顺序=用户级 → 项目级 → 附加，
  目录内按文件名排序；同名工具冲突 → 后加载者拒绝（登记可见）。
- 协议：模块导出 `register(api)`；导入失败/无 register/register 抛错 → broken（不阻断），
  该扩展注册事务性丢弃（broken 不半生效）。
- 信任：扩展 = 进程内完全信任代码（同 pi 语义）；`extension_enabled=false` 整体关闭。
- V1 钩子只读（返回值忽略、不得修改事件对象）；tool_call 干预留二期（设计 §2.3）。
"""
import hashlib
import importlib
import importlib.util
import json
import logging
import os
import pathlib
import re
from dataclasses import dataclass, field

from wuxing.protocols import Tool, ToolResult

logger = logging.getLogger(__name__)

# 最保守缺省（设计 §2.2）：未显式声明能力 → 全禁 → Registry 默认拒绝执行
DEFAULT_PERMISSION = {"read": False, "write": False, "execute": False,
                      "network": False, "destructive": False}


class ExtensionTool(Tool):
    """扩展工具适配器：统一 Tool 协议（白名单/守卫/权限/统计链同内置）。"""

    is_extension = True

    def __init__(self, *, name, description, parameters, execute,
                 domains=("execute",), permission=None, source=""):
        self._name = str(name)
        self._description = str(description or "")
        self._schema = dict(parameters or {})
        self._exec = execute
        self.domains = tuple(domains or ())
        self._permission = dict(permission or DEFAULT_PERMISSION)
        self.source = str(source)

    def name(self): return self._name
    def description(self): return self._description
    def input_schema(self): return self._schema
    def permission(self): return dict(self._permission)

    def execute(self, **kwargs) -> ToolResult:
        """返回值归一（设计 §2.2）：dict/str → ok；异常 → error（走修复提示链）。"""
        try:
            result = self._exec(**kwargs)
        except Exception as e:  # 扩展异常不挂引擎——结构化返回给模型
            return ToolResult(status="error", tool_name=self._name,
                              error=f"{type(e).__name__}: {e}")
        if isinstance(result, ToolResult):
            if not result.tool_name:
                result.tool_name = self._name
            return result
        if isinstance(result, (dict, list)):
            content = json.dumps(result, ensure_ascii=False)
        else:
            content = "" if result is None else str(result)
        return ToolResult(status="ok", content=content, tool_name=self._name)


def normalize_tool_verdict(res):
    """E3-2（P0）：tool_call 钩子返回值规范化 → {decision, reason?, updated_input?}。

    - 新契约：{"decision": "allow"|"deny"|"ask", "reason", "updated_input"}；
    - 旧契约兼容：{"deny": str} ≡ deny；{"args": {...}} ≡ allow + updated_input；
    - 非契约返回（None/未知 dict）→ None（忽略）。
    """
    if not isinstance(res, dict):
        return None
    decision = str(res.get("decision") or "")
    reason = str(res.get("reason") or "")
    updated = res.get("updated_input")
    if decision not in ("allow", "deny", "ask"):
        if res.get("deny"):
            decision = "deny"
            reason = str(res.get("deny"))
        elif isinstance(updated, dict) or isinstance(res.get("args"), dict):
            decision = "allow"
        else:
            return None
    if not isinstance(updated, dict):
        updated = res.get("args") if isinstance(res.get("args"), dict) else None
    out = {"decision": decision}
    if reason:
        out["reason"] = reason
    if updated is not None:
        out["updated_input"] = updated
    return out


class EventDispatcher:
    """事件钩子分发（D3 V1 只读）：扩展先、原 on_event 后；钩子异常隔离。"""

    def __init__(self, trace=None):
        self._hooks = {}
        self._trace = trace

    def add(self, event_name: str, handler, source: str = "") -> None:
        self._hooks.setdefault(str(event_name), []).append((str(source), handler))

    def has_hooks(self) -> bool:
        return bool(self._hooks)

    def dispatch_first(self, event):
        """E2-2：依次调用钩子，首个非 None 返回值胜出；异常隔离（继续下一个）。"""
        name = type(event).__name__
        for source, handler in self._hooks.get(name, ()):
            try:
                res = handler(event)
            except Exception as e:
                logger.warning("扩展钩子异常 [%s] %s: %s", source, name, e)
                if self._trace is not None:
                    self._trace.log("extension_hook_error", "", "",
                                    name=source, event_name=name,
                                    reason=f"{type(e).__name__}: {e}")
                continue
            if res is not None:
                return res
        return None

    def dispatch(self, event) -> None:
        name = type(event).__name__
        for source, handler in self._hooks.get(name, ()):
            try:
                handler(event)
            except Exception as e:  # 隔离：不传播、不阻断任务（设计 §2.3/§4）
                logger.warning("扩展钩子异常 [%s] %s: %s", source, name, e)
                if self._trace is not None:
                    self._trace.log("extension_hook_error", "", "",
                                    name=source, event_name=name,
                                    reason=f"{type(e).__name__}: {e}")

    def dispatch_merge(self, event):
        """E3-2（P0）：收集全部钩子决策并按 **deny > ask > allow** 合并。

        - 最严决策胜出（后序 allow 不得放宽前序 deny/ask——安全优先）；
        - updated_input 取首个提供者（注册顺序）；
        - 异常隔离（warning + trace，继续）；无有效决策 → None。
        """
        name = type(event).__name__
        merged = None
        first_updated = None
        for source, handler in self._hooks.get(name, ()):
            try:
                res = handler(event)
            except Exception as e:
                logger.warning("扩展钩子异常 [%s] %s: %s", source, name, e)
                if self._trace is not None:
                    self._trace.log("extension_hook_error", "", "",
                                    name=source, event_name=name,
                                    reason=f"{type(e).__name__}: {e}")
                continue
            v = normalize_tool_verdict(res)
            if v is None:
                continue
            if first_updated is None and v.get("updated_input"):
                first_updated = v["updated_input"]
            if merged is None:
                merged = {"decision": v["decision"]}
                if v.get("reason"):
                    merged["reason"] = v["reason"]
                continue
            _rank = {"allow": 0, "ask": 1, "deny": 2}
            if _rank[v["decision"]] > _rank[merged["decision"]]:
                merged["decision"] = v["decision"]
                if v.get("reason"):
                    merged["reason"] = v["reason"]
                else:
                    merged.pop("reason", None)
        if merged is not None and first_updated is not None:
            merged["updated_input"] = first_updated
        return merged

    def dispatch_collect(self, event) -> list:
        """E3-2（P1）：收集全部钩子返回值（非 None；异常隔离）——注入类事件用。"""
        name = type(event).__name__
        out: list = []
        for source, handler in self._hooks.get(name, ()):
            try:
                res = handler(event)
            except Exception as e:
                logger.warning("扩展钩子异常 [%s] %s: %s", source, name, e)
                if self._trace is not None:
                    self._trace.log("extension_hook_error", "", "",
                                    name=source, event_name=name,
                                    reason=f"{type(e).__name__}: {e}")
                continue
            if res is not None:
                out.append(res)
        return out

    def wrap(self, on_event):
        """组合器：先扩展 handlers、后原 on_event；无钩子原样返回（零行为）。"""
        if getattr(on_event, "_wuxing_ext_wrapped", False):
            return on_event  # 幂等：防 confirm_units → confirm_unit 双重包装
        if not self._hooks:
            return on_event

        def _composite(event):
            self.dispatch(event)
            if on_event is not None:
                on_event(event)

        _composite._wuxing_ext_wrapped = True
        return _composite


def user_extensions_dir() -> pathlib.Path:
    """用户级扩展目录（~/.wuxing/extensions）——测试经 monkeypatch 隔离。"""
    return pathlib.Path(os.path.expanduser("~")) / ".wuxing" / "extensions"


def resolve_extension_dirs(workdir, extra=None) -> list:
    """扩展目录清单：用户级 → 项目级 → 附加（相对路径按工作区解析）。"""
    workdir = pathlib.Path(workdir)
    dirs = [user_extensions_dir(), workdir / ".wuxing" / "extensions"]
    for d in (extra or ()):
        p = pathlib.Path(d)
        dirs.append(p if p.is_absolute() else workdir / p)
    return dirs


@dataclass
class ToolCallRequested:
    """E2-2：工具调用前置事件（干预钩子可放行/改参/拦截）。"""

    name: str
    args: dict


# E2-UI：命令参数声明（逐字段表单 + 机制侧校验/转换）
_COMMAND_ARG_TYPES = ("str", "int", "float", "bool")


def _arg_type_ok(typ: str, value) -> bool:
    if typ == "str":
        return isinstance(value, str)
    if typ == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if typ == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, bool)


def _normalize_command_args(args) -> list:
    """E2-UI：命令参数声明规范化 → [{name,label,type,required,default}]。"""
    out: list = []
    seen: set = set()
    for raw in (args or []):
        if not isinstance(raw, dict):
            raise TypeError(f"命令参数声明必须是对象：{raw!r}")
        name = str(raw.get("name") or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", name):
            raise ValueError(
                f"非法参数名：{name!r}（小写字母开头；字母/数字/下划线）")
        if name in seen:
            raise ValueError(f"重复参数名：{name}")
        seen.add(name)
        typ = str(raw.get("type") or "str")
        if typ not in _COMMAND_ARG_TYPES:
            raise ValueError(f"参数 {name} 类型非法：{typ!r}（str/int/float/bool）")
        default = raw.get("default")
        if default is not None and not _arg_type_ok(typ, default):
            raise ValueError(f"参数 {name} 默认值与类型 {typ} 不符：{default!r}")
        out.append({"name": name, "label": str(raw.get("label") or name),
                    "type": typ, "required": bool(raw.get("required", False)),
                    "default": default})
    return out


def coerce_command_args(schema, values) -> tuple:
    """E2-UI：按声明转换/补默认（返回 (值, 错误)——错误非空 = 校验失败）。"""
    src = dict(values or {})
    out: dict = {}
    declared: set = set()
    for spec in (schema or []):
        name = str(spec.get("name"))
        typ = str(spec.get("type") or "str")
        declared.add(name)
        raw = src.get(name)
        if raw is None:
            raw = spec.get("default")
            if raw is None:
                if spec.get("required"):
                    return {}, f"缺少必填参数：{spec.get('label') or name}"
                continue
        try:
            if typ == "str":
                out[name] = str(raw)
            elif typ == "int":
                if isinstance(raw, bool):
                    raise ValueError
                out[name] = int(raw)
            elif typ == "float":
                if isinstance(raw, bool):
                    raise ValueError
                out[name] = float(raw)
            else:
                out[name] = (raw if isinstance(raw, bool)
                             else str(raw).strip().lower()
                             in ("1", "true", "yes", "on"))
        except (TypeError, ValueError):
            return {}, f"参数 {spec.get('label') or name} 需要 {typ} 类型"
    for k, v in src.items():   # 未声明键透传（CLI 直调兼容）
        if k not in declared:
            out[k] = v
    return out, ""


class ExtensionAPI:
    """扩展注册面（模块 register(api) 的回调入口）。

    事务性：注册先入暂存区，load_extensions 在 register() 成功返回后统一提交——
    register 中途抛错 = 该扩展零生效（broken 不半生效）。
    """

    def __init__(self, workdir, source: str, log_fn):
        self.workdir = pathlib.Path(workdir)
        self._source = source
        self._log_fn = log_fn
        self.pending_tools: list = []
        self.pending_hooks: list = []
        self.pending_segments: list = []
        self.pending_commands: list = []

    def log(self, msg) -> None:
        self._log_fn(self._source, str(msg))

    def on(self, event_name: str, handler) -> None:
        if not callable(handler):
            raise TypeError("handler 必须可调用")
        self.pending_hooks.append((str(event_name), handler))

    def add_prompt_segment(self, text, *, domains=None) -> None:
        """E2-1：注入提示词段（非空 ≤2000 字符；domains=None=全单元）。"""
        t = str(text or "").strip()
        if not t:
            raise ValueError("提示词段不能为空")
        if len(t) > 2000:
            raise ValueError("提示词段超过 2000 字符上限")
        self.pending_segments.append({
            "source": self._source, "text": t,
            "domains": tuple(str(d) for d in (domains or ())) or None})

    def register_command(self, name, handler, *, description="", args=None) -> None:
        """E2-3/E2-UI：注册扩展命令（name: ^[a-z][a-z0-9-]{0,40}$；handler(args) → 文本）。

        args：可选参数声明（[{name,label,type,required,default}]）——UI 逐字段表单；
        运行期由 coerce_command_args 校验/转换（机制侧为准）。
        """
        nm = str(name or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,40}", nm):
            raise ValueError(f"非法命令名：{name!r}（小写字母/数字/连字符）")
        if not callable(handler):
            raise TypeError("handler 必须可调用")
        self.pending_commands.append({
            "name": nm, "description": str(description or ""),
            "handler": handler, "source": self._source,
            "args": _normalize_command_args(args)})

    def register_tool(self, *, name, description, parameters, execute,
                      domains=("execute",), permission=None) -> None:
        if not callable(execute):
            raise TypeError("execute 必须可调用")
        self.pending_tools.append(ExtensionTool(
            name=name, description=description, parameters=parameters,
            execute=execute, domains=domains, permission=permission,
            source=self._source))


@dataclass
class ExtensionRecord:
    """成功加载的扩展（名 + 路径——trace/审计可见）。"""
    name: str
    path: str


@dataclass
class ExtensionLoadResult:
    """加载结果：loaded（成功）/ tools（注册成功或收集的扩展工具）/
    problems（失败与冲突——报告注记与 trace 的可见性来源）/ dispatcher。"""
    loaded: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    prompt_segments: list = field(default_factory=list)
    commands: list = field(default_factory=list)
    dispatcher: "EventDispatcher" = field(default_factory=EventDispatcher)

    def summary_note(self) -> str:
        if not self.problems:
            return ""
        return ("[扩展] " + str(len(self.problems)) + " 个加载失败："
                + "；".join(self.problems))


def _entry_points():
    """E2-4：pip 入口点发现（组 `wuxing.extensions`；值 = pkg.module[:attr]）。"""
    try:
        from importlib.metadata import entry_points
        return list(entry_points(group="wuxing.extensions"))
    except Exception:
        return []


def load_extensions(workdir, *, enabled=True, dirs=None, trace=None,
                    registry=None, enabled_names=None,
                    disabled_names=()) -> ExtensionLoadResult:
    """扫描并加载扩展（零行为：开关关闭/目录不存在 → 空结果）。

    registry（ToolRegistry | None）：提供时注册扩展工具（域白名单合并）；
    None 时仅收集（加载器单测/预览场景）。
    """
    result = ExtensionLoadResult(dispatcher=EventDispatcher(trace=trace))
    if not enabled:
        return result

    def _log(source, msg):
        logger.info("[ext:%s] %s", source, msg)
        if trace is not None:
            trace.log("extension_log", "", "", name=source, msg=str(msg))

    def _error(name, reason):
        result.problems.append(f"{name}（{reason}）")
        if trace is not None:
            trace.log("extension_error", "", "", name=name, reason=reason)

    # E2-4：装配预设过滤（enable 非空=白名单；disable 恒生效；"*"=通配）
    _allow = None if enabled_names is None else {str(n) for n in enabled_names}
    _deny = {str(n) for n in (disabled_names or ())}

    def _allowed(name: str) -> bool:
        if "*" in _deny or name in _deny:
            return False
        if _allow is None:
            return True
        return name in _allow or "*" in _allow

    def _commit(api, name: str, src) -> None:
        for tool in api.pending_tools:
            taken = (registry.get(tool.name()) is not None
                     if registry is not None
                     else any(t.name() == tool.name() for t in result.tools))
            if taken:
                _error(name, f"工具名冲突：{tool.name()}——拒绝登记")
                continue
            if registry is not None:
                registry.register_extension(tool, tool.domains)
            result.tools.append(tool)
        for event_name, handler in api.pending_hooks:
            result.dispatcher.add(event_name, handler, source=name)
        for seg in api.pending_segments:
            result.prompt_segments.append(seg)
        for cmd in api.pending_commands:
            taken = any(c["name"] == cmd["name"] for c in result.commands)
            if taken:
                _error(name, f"命令名冲突：{cmd['name']}——拒绝登记")
                continue
            result.commands.append(cmd)
        result.loaded.append(ExtensionRecord(name=name, path=str(src)))
        if trace is not None:
            trace.log("extension_loaded", "", "", name=name, path=str(src))

    for root in (dirs or resolve_extension_dirs(workdir)):
        root = pathlib.Path(root)
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.py")):
            if path.name.startswith("_"):
                continue  # __init__.py / 辅助模块不入扩展面
            name = path.stem
            if not _allowed(name):
                continue
            module_name = ("wuxing_ext_" + hashlib.sha1(
                str(path.resolve()).encode("utf-8")).hexdigest()[:12])
            try:
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"无法构建模块 spec：{path}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as e:
                _error(name, f"导入失败：{type(e).__name__}: {e}")
                continue
            register = getattr(module, "register", None)
            if not callable(register):
                _error(name, "缺少 register(api) 入口")
                continue
            api = ExtensionAPI(workdir=workdir, source=name, log_fn=_log)
            try:
                register(api)
            except Exception as e:
                _error(name, f"注册失败：{type(e).__name__}: {e}")
                continue  # 事务性：暂存区丢弃——broken 零生效
            # ── 提交（register 成功返回后）──
            _commit(api, name, path)
    # E2-4：pip 入口点扩展（组 wuxing.extensions）
    for ep in _entry_points():
        name = str(getattr(ep, "name", "") or "ep")
        if not _allowed(name):
            continue
        try:
            module = ep.load()
        except Exception as e:
            _error(name, f"入口点加载失败：{type(e).__name__}: {e}")
            continue
        register = getattr(module, "register", None)
        if not callable(register):
            _error(name, "缺少 register(api) 入口")
            continue
        api = ExtensionAPI(workdir=workdir, source=name, log_fn=_log)
        try:
            register(api)
        except Exception as e:
            _error(name, f"注册失败：{type(e).__name__}: {e}")
            continue
        _commit(api, name, f"entry-point:{name}")
    return result
