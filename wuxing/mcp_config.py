"""MCP 统一便携根（P2 · 2026-10-18 用户裁决 A）。

位置：
  - 用户：`~/.agents/mcp.json`
  - 项目：`<workspace>/.agents/mcp.json`（默认不加载；需用户级全局
    `mcp_project_enabled=true` 或 env `WUXING_MCP_PROJECT_ENABLED=1`）

格式：`{"mcpServers": {"<name>": {command|url, args?, headers?, permissions?, env?}}}`
合并：`config.jsonc:mcp_servers` 为底层；用户便携文件覆盖；项目便携文件
（信任开启时）再覆盖。同名 server 高者胜。
"""
from __future__ import annotations

import pathlib

from wuxing.config_loader import global_mcp_project_enabled, parse_jsonc
from wuxing.config_schema import validate_config


def _user_mcp_path() -> pathlib.Path:
    return pathlib.Path.home() / ".agents" / "mcp.json"


def _project_mcp_path(workdir: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(workdir) / ".agents" / "mcp.json"


def load_mcp_json(path: pathlib.Path) -> list[dict]:
    """读取 `mcpServers` map → 配置项列表（带 name）；非法输入 loud 失败。"""
    p = pathlib.Path(path)
    if not p.exists():
        return []
    try:
        raw = parse_jsonc(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{p} 读取/解析失败：{exc}") from exc
    if not isinstance(raw, dict):
        raise TypeError(f"{p} 顶层必须是对象")
    servers = raw.get("mcpServers")
    if not isinstance(servers, dict):
        raise TypeError(f"{p} 必须包含 mcpServers 对象")

    items: list[dict] = []
    for name, entry in servers.items():
        if not isinstance(name, str) or not name:
            raise TypeError(f"{p} mcpServers 的 server 名必须是非空字符串")
        if not isinstance(entry, dict):
            raise TypeError(f"{p} mcpServers.{name} 必须是对象")
        if "name" in entry:
            raise ValueError(
                f"{p} mcpServers.{name} 不得再含 name（名称由 map key 决定）"
            )
        items.append({"name": name, **entry})

    errors = validate_config({"mcp_servers": items})
    if errors:
        raise ValueError(f"{p} 校验失败：" + "；".join(errors))
    for item in items:
        if "args" in item and not isinstance(item["args"], list):
            raise ValueError(f"{p} mcpServers.{item['name']}.args 必须是数组")
        for field in ("permissions", "headers", "env"):
            if field in item and not isinstance(item[field], dict):
                raise ValueError(
                    f"{p} mcpServers.{item['name']}.{field} 必须是对象"
                )
    return items


def merge_mcp_servers(base: list[dict], overlay: list[dict]) -> list[dict]:
    """按 name 合并；overlay 同名覆盖，顺序稳定（base 顺序 + 新项追加）。"""
    merged = [dict(item) for item in base]
    index = {item["name"]: i for i, item in enumerate(merged)}
    for item in overlay:
        name = item["name"]
        if name in index:
            merged[index[name]] = dict(item)
        else:
            index[name] = len(merged)
            merged.append(dict(item))
    return merged


def resolve_mcp_servers(
    workdir: pathlib.Path,
    config_servers: list | None,
    *,
    enable_project: bool | None = None,
    global_config_dir: pathlib.Path | None = None,
    user_mcp_path: pathlib.Path | None = None,
    project_mcp_path: pathlib.Path | None = None,
) -> tuple[list[dict], list[str]]:
    """解析 MCP 配置来源，返回 (servers, sources)。

    全局/用户级始终加载（长期有效）；项目级仅在 enable_project（默认取全局
    信任开关）为真时加载。sources 只含路径/层名，不含 token/密钥。
    """
    base = [dict(item) for item in (config_servers or [])]
    sources: list[str] = []
    if base:
        sources.append("config.jsonc:mcp_servers")

    user = pathlib.Path(user_mcp_path) if user_mcp_path else _user_mcp_path()
    if user.exists():
        base = merge_mcp_servers(base, load_mcp_json(user))
        sources.append(f"user:{user}")

    project = (
        pathlib.Path(project_mcp_path)
        if project_mcp_path
        else _project_mcp_path(workdir)
    )
    if project.exists():
        enabled = (
            bool(enable_project)
            if enable_project is not None
            else global_mcp_project_enabled(global_config_dir)
        )
        if enabled:
            base = merge_mcp_servers(base, load_mcp_json(project))
            sources.append(f"project:{project}")
        else:
            sources.append(f"project:{project} (ignored: mcp_project_enabled=false)")
    return base, sources
