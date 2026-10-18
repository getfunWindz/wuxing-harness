"""SEC2 扩展分发审查：注册面枚举 + 风险标注（设计 §3，裁决 A）。

用法（模块）：inspect_extension(target, static=False) / risk_flags / render_report
CLI：python -m scripts.check_extension <entry-point|package|path> [--static] [--json]
安全边界（如实披露）：动态模式**执行扩展代码**（进程内信任语义的固有事实）；
静态模式仅扫元数据/源码，覆盖有限。工具不是沙箱。
"""
from __future__ import annotations

import ast
import dataclasses
import importlib
import importlib.util
import pathlib

from wuxing.extensions import ExtensionAPI

_DANGER_PERMS = ("execute", "network", "destructive", "write")
_SUSPICIOUS = ("import subprocess", "import socket", "os.system", "eval(", "exec(")


@dataclasses.dataclass
class Flag:
    kind: str
    detail: str
    severity: str = "warn"  # danger | warn | info


@dataclasses.dataclass
class ExtensionAudit:
    target: str
    mode: str  # dynamic | static
    tools: list = dataclasses.field(default_factory=list)
    hooks: list = dataclasses.field(default_factory=list)
    prompt_segments: list = dataclasses.field(default_factory=list)
    commands: list = dataclasses.field(default_factory=list)
    source_files: list = dataclasses.field(default_factory=list)
    pyproject: str = ""  # C3（E0-4）：静态模式发现的 pyproject.toml 路径


def _load_module(target):
    """按路径（目录/文件）或模块名加载扩展模块；返回 (mod, files)。"""
    p = pathlib.Path(str(target))
    if p.exists():
        root = p.resolve()
        init = root if root.is_file() else root / "__init__.py"
        if root.is_dir() and not init.is_file():
            # 打包根（如 docs/examples 扩展包）：找唯一子包
            candidates = sorted(root.glob("*/__init__.py"))
            if len(candidates) != 1:
                raise ValueError(
                    f"目录下无法定位唯一扩展包（含 __init__.py 的子目录数={len(candidates)}）：{target}")
            init = candidates[0]
        spec = importlib.util.spec_from_file_location(
            "ext_audit_target", init,
            submodule_search_locations=([str(root)] if root.is_dir() else None))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        files = (sorted(str(x) for x in root.rglob("*.py"))
                 if root.is_dir() else [str(init)])
        return mod, files
    mod = importlib.import_module(str(target))
    src = getattr(mod, "__file__", None)
    return mod, ([src] if src else [])


def inspect_extension(target, *, static: bool = False) -> ExtensionAudit:
    audit = ExtensionAudit(target=str(target),
                           mode="static" if static else "dynamic")
    p = pathlib.Path(str(target))
    if p.is_dir():
        audit.source_files = sorted(str(x) for x in p.rglob("*.py"))
    if static:
        pp = _find_pyproject(p)
        if pp is not None:
            audit.pyproject = str(pp)
        return audit
    mod, files = _load_module(target)
    if files:
        audit.source_files = files
    register = getattr(mod, "register", None)
    if register is None:
        raise ValueError(f"扩展缺少 register(api)：{target}")
    api = ExtensionAPI(pathlib.Path.cwd(), source=str(target),
                       log_fn=lambda *_: None)
    register(api)  # 动态模式：执行扩展代码（设计 §3.6 明示）
    audit.tools = [{"name": t.name(), "description": t.description(),
                    "domains": list(t.domains),
                    "permission": dict(t.permission())}
                   for t in api.pending_tools]
    audit.hooks = [h[0] for h in api.pending_hooks]
    audit.prompt_segments = [str(s.get("text", ""))[:80]
                             for s in api.pending_segments]
    audit.commands = [str(c.get("name", "")) for c in api.pending_commands]
    return audit


def _find_pyproject(target: pathlib.Path):
    """静态定位 pyproject.toml（目录本身——就近原则，不向上追溯）。"""
    base = target if target.is_dir() else target.parent
    cand = base / "pyproject.toml"
    return cand if cand.is_file() else None


def _pyproject_entry_point_names(text: str) -> list:
    """尽力解析 [project.entry-points] 名单（tomllib 3.11+；3.10 无解析器 → []）。"""
    try:
        import tomllib
    except ImportError:
        return []
    try:
        data = tomllib.loads(text)
    except Exception:
        return []
    eps = ((data.get("project") or {}).get("entry-points") or {})
    names = []
    for group, items in sorted(eps.items()):
        if isinstance(items, dict):
            names += [f"{group}:{k}" for k in sorted(items)]
    return names


def _static_pyproject_flags(audit: ExtensionAudit) -> list:
    """C3（E0-4/P2-2）：静态 pyproject 提示——entry-points 可能注册扩展面。"""
    if not audit.pyproject:
        return []
    try:
        text = pathlib.Path(audit.pyproject).read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return []
    if "entry-points" not in text:
        return []
    names = _pyproject_entry_point_names(text)
    detail = "pyproject.toml 声明 entry-points"
    detail += ("：" + "、".join(names[:5])) if names else "（静态仅提示——未解析名单）"
    detail += "——需动态审查核验真实注册面；分发建议显式声明版本约束"
    return [Flag("pyproject-entry-points", detail, "info")]


def _static_source_flags(audit: ExtensionAudit) -> list:
    """审查修复（2026-09-30）：静态源码扫描——权限字面量 + register 存在性。

    不执行代码的门控面（设计 §3.2）：AST 解析（注释/字符串不误报）；
    解析失败的文件跳过（覆盖不足如实体现）。
    """
    flags: list = []
    has_register = False
    for f in audit.source_files:
        p = pathlib.Path(f)
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in tree.body:
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "register"):
                has_register = True
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                        and key.value in _DANGER_PERMS
                        and isinstance(value, ast.Constant)
                        and value.value is True):
                    flags.append(Flag(
                        "dangerous-permission-literal",
                        f"{p.name}:{getattr(node, 'lineno', '?')} "
                        f"声明 {key.value}=True（静态）", "danger"))
    if not has_register:
        flags.append(Flag(
            "missing-register",
            "未发现顶层 register(api)（静态检测——动态加载将失败）", "warn"))
    return flags


def risk_flags(audit: ExtensionAudit) -> list:
    flags = []
    if audit.mode == "static":
        # 审查修复（2026-09-30）：静态模式补源码字面量/register 扫描
        flags.extend(_static_source_flags(audit))
        # C3（E0-4/P2-2）：pyproject entry-points 提示（info）
        flags.extend(_static_pyproject_flags(audit))
    for t in audit.tools:
        perm = dict(t.get("permission") or {})
        bad = [k for k in _DANGER_PERMS if perm.get(k)]
        if bad:
            flags.append(Flag("dangerous-permission",
                              f"{t.get('name', '?')}: {','.join(bad)}",
                              "danger"))
    text = ""
    for f in audit.source_files:
        try:
            text += pathlib.Path(f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    for needle in _SUSPICIOUS:
        if needle in text:
            flags.append(Flag("suspicious-import", needle, "warn"))
    return flags


def render_report(audit: ExtensionAudit) -> str:
    lines = [f"# 扩展审查报告：{audit.target}（{audit.mode}）", ""]
    lines.append(f"- 工具 {len(audit.tools)} · 钩子 {len(audit.hooks)} · "
                 f"提示词段 {len(audit.prompt_segments)} · 命令 {len(audit.commands)}")
    for t in audit.tools:
        perm = dict(t.get("permission") or {})
        on = [k for k, v in perm.items() if v]
        lines.append(f"- 工具 {t.get('name')}：权限 {on or ['无']}")
    flags = risk_flags(audit)
    if flags:
        lines.append("")
        lines.append("## 风险标注")
        for f in flags:
            lines.append(f"- [{f.severity}] {f.kind}：{f.detail}")
    return "\n".join(lines)
