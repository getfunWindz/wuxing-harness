"""P2：MCP 统一便携根 `.agents/mcp.json`（用户/项目）+ 全局信任开关 A。"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

from wuxing.engine import Engine
from wuxing.mcp_config import (
    load_mcp_json,
    merge_mcp_servers,
    resolve_mcp_servers,
)

_SERVER = str(pathlib.Path(__file__).with_name("mcp_echo_server.py"))


def _write_mcp(path: pathlib.Path, servers: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"mcpServers": servers}, ensure_ascii=False),
        encoding="utf-8",
    )


def _echo_server() -> dict:
    return {"command": sys.executable, "args": [_SERVER]}


def test_load_mcp_json_map_and_jsonc(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(
        '// comment\n{"mcpServers": {"a": {"command": "python", '
        '"args": ["-m", "x"], "permissions": {"read": true}}}}',
        encoding="utf-8",
    )
    items = load_mcp_json(path)
    assert items == [{
        "name": "a",
        "command": "python",
        "args": ["-m", "x"],
        "permissions": {"read": True},
    }]


def test_load_mcp_json_rejects_missing_mcp_servers(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text('{"servers": {}}', encoding="utf-8")
    with pytest.raises(TypeError, match="mcpServers"):
        load_mcp_json(path)


def test_load_mcp_json_rejects_entry_name(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(
        '{"mcpServers": {"a": {"name": "b", "command": "python"}}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="不得再含 name"):
        load_mcp_json(path)


def test_merge_mcp_servers_overlay_wins():
    base = [{"name": "a", "command": "old"}, {"name": "b", "command": "b"}]
    overlay = [{"name": "a", "command": "new"}, {"name": "c", "command": "c"}]
    merged = merge_mcp_servers(base, overlay)
    assert [item["name"] for item in merged] == ["a", "b", "c"]
    assert merged[0]["command"] == "new"


def test_resolve_user_mcp_overrides_config(tmp_path):
    user = tmp_path / "user_mcp.json"
    _write_mcp(user, {"a": {"command": "user"}})
    servers, sources = resolve_mcp_servers(
        tmp_path / "ws",
        [{"name": "a", "command": "config"}],
        user_mcp_path=user,
        project_mcp_path=tmp_path / "no_project.json",
        enable_project=False,
    )
    assert servers[0]["command"] == "user"
    assert any("user_mcp.json" in source for source in sources)


def test_project_mcp_ignored_by_default(tmp_path):
    project = tmp_path / "ws" / ".agents" / "mcp.json"
    _write_mcp(project, {"p": {"command": "project"}})
    servers, sources = resolve_mcp_servers(
        tmp_path / "ws",
        [],
        user_mcp_path=tmp_path / "no_user.json",
        project_mcp_path=project,
        enable_project=False,
    )
    assert servers == []
    assert any("ignored" in source for source in sources)


def test_project_mcp_loaded_when_enabled(tmp_path):
    project = tmp_path / "ws" / ".agents" / "mcp.json"
    _write_mcp(project, {"p": {"command": "project"}})
    servers, sources = resolve_mcp_servers(
        tmp_path / "ws",
        [],
        user_mcp_path=tmp_path / "no_user.json",
        project_mcp_path=project,
        enable_project=True,
    )
    assert [item["name"] for item in servers] == ["p"]
    assert any("project:" in source for source in sources)


def test_global_config_flag_enables_project(tmp_path):
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "config.jsonc").write_text(
        '{"mcp_project_enabled": true}', encoding="utf-8")
    project = tmp_path / "ws" / ".agents" / "mcp.json"
    _write_mcp(project, {"p": {"command": "project"}})
    servers, _ = resolve_mcp_servers(
        tmp_path / "ws",
        [],
        user_mcp_path=tmp_path / "no_user.json",
        project_mcp_path=project,
        global_config_dir=global_dir,
    )
    assert [item["name"] for item in servers] == ["p"]


def test_env_flag_enables_project(tmp_path, monkeypatch):
    monkeypatch.setenv("WUXING_MCP_PROJECT_ENABLED", "1")
    project = tmp_path / "ws" / ".agents" / "mcp.json"
    _write_mcp(project, {"p": {"command": "project"}})
    servers, _ = resolve_mcp_servers(
        tmp_path / "ws",
        [],
        user_mcp_path=tmp_path / "no_user.json",
        project_mcp_path=project,
        global_config_dir=tmp_path / "no_global",
    )
    assert [item["name"] for item in servers] == ["p"]


def test_workspace_config_cannot_enable_project_mcp(tmp_path, monkeypatch):
    import wuxing.config_loader as cl
    import wuxing.mcp_config as mc

    global_dir = tmp_path / "global"
    global_dir.mkdir()
    monkeypatch.setattr(cl, "_global_config_dir", lambda: global_dir)
    monkeypatch.setattr(mc, "_user_mcp_path", lambda: tmp_path / "no_user.json")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "config.jsonc").write_text(
        '{"mcp_project_enabled": true}', encoding="utf-8")
    _write_mcp(ws / ".agents" / "mcp.json", {"p": _echo_server()})

    eng = Engine(workdir=ws)
    assert eng.cfg.mcp_project_enabled is False
    assert eng._mcp_cfgs == []


def test_engine_loads_project_mcp_when_global_enabled(tmp_path, monkeypatch):
    import wuxing.config_loader as cl
    import wuxing.mcp_config as mc

    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "config.jsonc").write_text(
        '{"mcp_project_enabled": true}', encoding="utf-8")
    monkeypatch.setattr(cl, "_global_config_dir", lambda: global_dir)
    monkeypatch.setattr(mc, "_user_mcp_path", lambda: tmp_path / "no_user.json")
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_mcp(ws / ".agents" / "mcp.json", {"p": _echo_server()})

    eng = Engine(workdir=ws)
    assert eng.cfg.mcp_project_enabled is True
    assert [cfg.name for cfg in eng._mcp_cfgs] == ["p"]
    assert any("project:" in source for source in eng._mcp_sources)
    status = eng.mcp_status()
    assert status["project_mcp_enabled"] is True
    assert any("project:" in source for source in status["sources"])


def test_engine_isolated_skips_project_mcp(tmp_path, monkeypatch):
    import wuxing.config_loader as cl
    import wuxing.mcp_config as mc

    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "config.jsonc").write_text(
        '{"mcp_project_enabled": true}', encoding="utf-8")
    monkeypatch.setattr(cl, "_global_config_dir", lambda: global_dir)
    monkeypatch.setattr(mc, "_user_mcp_path", lambda: tmp_path / "no_user.json")
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_mcp(ws / ".agents" / "mcp.json", {"p": _echo_server()})

    eng = Engine(workdir=ws, isolated=True)
    assert eng._mcp_cfgs == []
