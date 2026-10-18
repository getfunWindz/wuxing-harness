"""配置读写契约（UI 重构阶段 3 · 引擎对齐项⑨）——壳设置中心的唯一入口。

- describe_config()  字段声明（含生效范围 scope：now / next / restart）
- effective_config(workdir)  三层生效值 + 来源（default / user / workspace）
- write_config(scope, values, workdir=None)  写入用户级 / 工作区级（merge 语义 + 校验）

纪律：key 不落盘（api_key_env 机制）；写入即校验（ConfigError 早报）；原子写。
"""
import hashlib
import json
import pathlib

from wuxing.atomic_write import atomic_write_text
from wuxing.config_loader import merge_configs, parse_jsonc
from wuxing.config_schema import FIELD_SPECS, validate_config


class ConfigError(ValueError):
    pass


class ConfigConflict(ConfigError):
    """revision 不匹配（外部编辑/多标签并发）——拒绝覆盖式写入。"""

    def __init__(self, current_revision: str):
        super().__init__("配置已被外部编辑（revision 不匹配）——已拒绝写入")
        self.current_revision = current_revision


def user_config_path() -> pathlib.Path:
    """用户级配置路径（默认 ~/.wuxing/config.jsonc；测试可 monkeypatch）。"""
    return pathlib.Path.home() / ".wuxing" / "config.jsonc"


def _file_revision(path: pathlib.Path) -> str:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        # 读不到文件 → 空修订：契约比对按缺省处理
        return ""


def config_revision(scope: str = "user", workdir=None) -> str:
    """目标层配置文件原文 sha1（缺文件 → ""）——外部编辑可检测（R3-1/D4）。"""
    if scope == "user":
        return _file_revision(user_config_path())
    if scope == "workspace" and workdir:
        return _file_revision(pathlib.Path(workdir) / ".wuxing" / "config.jsonc")
    return ""


def describe_config() -> list[dict]:
    """字段声明（壳据此渲染设置项）。scope 缺省 = next（下个任务生效）。"""
    out = []
    for s in FIELD_SPECS:
        out.append({
            "name": s.name,
            "type": s.type,
            "default": s.default,
            "desc": s.desc,
            "scope": getattr(s, "scope", "next"),
            "enum": list(s.enum) if s.enum else None,
        })
    return out


def _read_layer(path) -> dict:
    p = pathlib.Path(path) if path else None
    if not (p and p.exists()):
        return {}
    try:
        data = parse_jsonc(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _layers(workdir) -> list[tuple[pathlib.Path, str]]:
    layers: list[tuple[pathlib.Path, str]] = [(user_config_path(), "user")]
    if workdir is not None:
        wd = pathlib.Path(workdir)
        layers += [
            (wd / ".wuxing" / "config.jsonc", "workspace"),
            (wd / "config.jsonc", "workspace"),
        ]
    return layers


def effective_config(workdir=None) -> dict:
    """三层生效值 + 来源（默认值兜底）；workdir=None → 用户级 + 默认（壳无工作区时）。"""
    merged: dict = {}
    sources: dict[str, str] = {}
    for path, source in _layers(workdir):
        data = _read_layer(path)
        if not data:
            continue
        merged = merge_configs(merged, data)
        for key in data:
            sources[key] = source
    values: dict = {}
    for s in FIELD_SPECS:
        if s.name in merged:
            values[s.name] = merged[s.name]
        else:
            values[s.name] = s.default
            sources[s.name] = "default"
    return {"values": values, "sources": sources}


def write_config(scope: str, values: dict, workdir=None,
                 replace_keys=(), revision: str | None = None) -> dict:
    """写入配置（merge 语义 + 完整校验 + 原子写）。

    scope="user"       → ~/.wuxing/config.jsonc
    scope="workspace"  → <workdir>/.wuxing/config.jsonc
    replace_keys       → 这些字段以 values 整体替换（不深合并——支持删除字典型条目）
    revision           → 非 None 则校验（不匹配 → ConfigConflict；R3-1 冲突协议）
    """
    if scope not in ("user", "workspace"):
        raise ConfigError("scope 必须为 user/workspace")
    if scope == "workspace" and not workdir:
        raise ConfigError("工作区级写入需要 workdir")
    if not isinstance(values, dict) or not values:
        raise ConfigError("写入内容必须为非空对象")
    known = {f.name for f in FIELD_SPECS}
    unknown = sorted(k for k in values if k not in known)
    if unknown:
        raise ConfigError(f"未知配置项：{', '.join(unknown)}")
    path = (user_config_path() if scope == "user"
            else pathlib.Path(workdir) / ".wuxing" / "config.jsonc")
    if revision is not None and revision != _file_revision(path):
        raise ConfigConflict(_file_revision(path))
    current = _read_layer(path)
    merged = merge_configs(current, dict(values))
    for key in replace_keys or ():
        if key in values:
            merged[key] = values[key]
    errors = validate_config(merged)
    if errors:
        raise ConfigError("配置校验失败: " + "; ".join(errors))
    atomic_write_text(
        path, json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    return {"ok": True, "scope": scope, "path": str(path),
            "written": sorted(values), "revision": _file_revision(path)}
