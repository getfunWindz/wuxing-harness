"""配置加载器（P11：JSONC 三层合并——全局→项目→工作区，merge 非 replace）。

- parse_jsonc：JSONC 手写解析（// 与 /* */ 注释容忍——不引依赖）
- merge_configs：深合并（非冲突保留，冲突后层覆盖——opencode 语义）
- load_config：三层发现（~/.wuxing ← {workdir}/.wuxing ← {workdir}）+ load 即校验
- ConfigError：校验失败早报（带字段定位）
"""
import json
import logging
import pathlib

from wuxing.config_schema import validate_config

logger = logging.getLogger(__name__)


class ConfigError(ValueError):
    pass


def parse_jsonc(raw: str) -> dict:
    """JSONC 解析：去注释（// 行注释、/* */ 块注释）后 json.loads。

    手写实现（不引依赖）：逐字符扫描，字符串内注释不误删。
    阶段 2 加固：BOM 剥离（Windows 编辑器常见）；未闭合块注释显式失败（不静默吞）。
    """
    raw = raw.lstrip("\ufeff")  # BOM 剥离
    out = []
    in_string = False
    escape = False
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        # 注释优先（字符串外）：`//` 行注释、`/* */` 块注释
        if not in_string:
            if ch == "/" and i + 1 < n and raw[i + 1] == "/":
                while i < n and raw[i] != "\n":
                    i += 1
                continue
            if ch == "/" and i + 1 < n and raw[i + 1] == "*":
                start = i
                i += 2
                while i + 1 < n and not (raw[i] == "*" and raw[i + 1] == "/"):
                    i += 1
                if i + 1 >= n:
                    raise ValueError(f"未闭合块注释（起始位置 {start}）")
                i += 2
                continue
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return json.loads("".join(out))


def merge_configs(base: dict, overlay: dict) -> dict:
    """深合并：非冲突保留，冲突 overlay 覆盖（opencode merge 语义）。"""
    result = dict(base)
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = merge_configs(result[k], v)
        else:
            result[k] = v
    return result


_LAYER_PATHS = [
    # (相对 workdir 的项目层/工作区层)
    ".wuxing/config.jsonc",
    "config.jsonc",
]


def _global_config_dir() -> pathlib.Path:
    """全局配置目录（~/.wuxing）——测试可隔离（conftest 夹具）。"""
    return pathlib.Path.home() / ".wuxing"


def load_config(workdir: pathlib.Path, global_config_dir: pathlib.Path | None = None) -> dict:
    """三层加载：全局（~/.wuxing/config.jsonc）← 项目（workdir/.wuxing/）← 工作区（workdir/）。

    缺失层跳过；合并后 load 即校验（ConfigError 早报）。
    """
    wd = pathlib.Path(workdir)
    gd = global_config_dir or _global_config_dir()
    layers = []
    # 全局层
    gp = gd / "config.jsonc"
    if gp.exists():
        layers.append(parse_jsonc(gp.read_text(encoding="utf-8")))
    # 项目层 + 工作区层
    for rel in _LAYER_PATHS:
        p = wd / rel
        if p.exists():
            layers.append(parse_jsonc(p.read_text(encoding="utf-8")))
    merged = {}
    for layer in layers:
        merged = merge_configs(merged, layer)
    # load 即校验
    errors = validate_config(merged)
    if errors:
        raise ConfigError("配置校验失败: " + "; ".join(errors))
    return merged


def load_global_config(global_config_dir: pathlib.Path | None = None) -> dict:
    """只读取全局层（~/.wuxing/config.jsonc）——用于不可被项目层覆盖的信任开关。"""
    gd = global_config_dir or _global_config_dir()
    gp = gd / "config.jsonc"
    if not gp.exists():
        return {}
    try:
        data = parse_jsonc(gp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # 全局信任文件不可读/非法 → fail-closed（不加载项目 MCP）
        logger.warning("全局配置读取失败（MCP 项目信任 fail-closed）：%s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def global_mcp_project_enabled(global_config_dir: pathlib.Path | None = None) -> bool:
    """P2-A：项目级 MCP 信任开关——仅用户级全局配置或 env 生效。

    工作区 config.jsonc 中的同名字段不被本函数读取；Engine 装载后还会用本值
    覆盖合并配置里的 mcp_project_enabled，防止项目自我授权。
    """
    import os
    env = os.environ.get("WUXING_MCP_PROJECT_ENABLED", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    return bool(load_global_config(global_config_dir).get("mcp_project_enabled", False))
