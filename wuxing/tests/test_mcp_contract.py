"""R3-2/T5：MCP 命名契约 + serverName 校验 + 白名单 + generation 回滚。"""
import pytest

from wuxing.config_schema import validate_config
from wuxing.tools.base import whitelist_accepts
from wuxing.tools.loader import merge_mcp_generation
from wuxing.tools.mcp_bridge import (
    McpServerConfig,
    McpToolAdapter,
    mcp_tool_name,
    transport_of,
    validate_server_name,
)


def _adapter(server="demo", tool="search"):
    return McpToolAdapter(server_name=server, tool_name=tool, description="",
                          input_schema={},
                          config=McpServerConfig(name=server, command="x"))


def test_tool_name_contract():
    assert mcp_tool_name("demo", "search") == "mcp__demo__search"
    assert _adapter().name() == "mcp__demo__search"


def test_server_name_validation():
    assert validate_server_name("demo-1_A") == "demo-1_A"
    for bad in ("", "has space", "a" * 33, "中文", "a.b"):
        with pytest.raises(ValueError):
            validate_server_name(bad)
    with pytest.raises(ValueError):
        McpServerConfig(name="bad name", command="x")


def test_transport_inference():
    assert transport_of(McpServerConfig(name="a", command="npx")) == "stdio"
    assert transport_of(
        McpServerConfig(name="a", url="https://mcp.example/v1")) == "streamable-http"
    assert transport_of(McpServerConfig(name="a")) == "stdio"


def test_whitelist_matches_new_contract():
    assert whitelist_accepts("mcp__demo__search", ["mcp:demo"], is_mcp=True)
    assert whitelist_accepts("mcp__demo__search", ["mcp:*"], is_mcp=True)
    assert not whitelist_accepts("mcp__demo__search", ["mcp:other"], is_mcp=True)
    assert not whitelist_accepts("mcp__demo__search", [], is_mcp=True)
    assert not whitelist_accepts("write_artifact", ["mcp:*"], is_mcp=False)


def test_generation_rollback():
    good = [_adapter("demo", "search"), _adapter("demo", "fetch")]
    assert len(merge_mcp_generation(good, ["read_file"])) == 2
    dup = [_adapter("demo", "search"), _adapter("demo", "search")]
    assert merge_mcp_generation(dup, []) == []
    assert merge_mcp_generation(good, ["mcp__demo__search"]) == []


def test_config_schema_mcp_validation():
    assert validate_config({"mcp_servers": [
        {"name": "demo", "command": "npx", "args": ["-y", "demo"]}]}) == []
    assert validate_config({"mcp_servers": [
        {"name": "remote", "url": "https://mcp.example/v1",
         "transport": "streamable-http"}]}) == []
    errs = validate_config({"mcp_servers": [
        {"name": "bad name", "command": "x"},
        {"name": "dup", "command": "x"},
        {"name": "dup", "url": "ftp://x"},
        {"name": "t", "command": "x", "transport": "weird"}]})
    joined = "\n".join(errs)
    assert "name" in joined and "[A-Za-z0-9_-]" in joined
    assert "重复" in joined
    assert "command" in joined and "url" in joined
    assert "transport" in joined


def test_open_stream_dispatch(monkeypatch):
    """T5b：传输分派——stdio 构造参数 / streamable-http 携带 url+headers。"""
    from wuxing.tools import mcp_bridge as mb
    captured = {}

    def fake_stdio(params):
        captured["stdio"] = params
        return object()

    def fake_http(url, headers=None):
        captured["http"] = (url, headers)
        return object()

    monkeypatch.setattr(mb, "stdio_client", fake_stdio)
    monkeypatch.setattr(mb, "_http_client", lambda: fake_http)
    mb._open_stream(McpServerConfig(name="a", command="npx"))
    assert captured["stdio"].command == "npx"
    mb._open_stream(McpServerConfig(name="b", url="https://mcp.example/v1",
                                    headers={"X-K": "1"}))
    assert captured["http"] == ("https://mcp.example/v1", {"X-K": "1"})
    assert mb._unpack_stream(("r", "w", "sid")) == ("r", "w")
