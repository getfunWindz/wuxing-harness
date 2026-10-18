"""TDD · O2-2 P3 T4：MCP 后端缝（BrowserBackend Protocol + 跨语言 COMMANDS 对拍）。

设计：§11.4——形态 B（外部 browser MCP 客户端）实现同一命令语义即可替换后端；
工具面/护栏/确认链不变。本测试锁定缝的事实来源（两侧命令集全等）。
"""
import pathlib
import re

import pytest

from wuxing import browser_channel
from wuxing.browser_channel import BrowserBackend, ChannelClient

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TS_PROTOCOL = (REPO_ROOT / "apps" / "shell" / "desktop" / "src"
               / "browser-protocol.ts")


def test_protocol_is_runtime_checkable():
    """ChannelClient 结构满足 BrowserBackend（未来 MCP 后端实现同一 Protocol）。"""
    client = ChannelClient("http://127.0.0.1:1", "token")
    assert isinstance(client, BrowserBackend)


def test_commands_parity_ts_python():
    """TS 主机 COMMANDS 与 Python 客户端 COMMANDS 全等（改一处必须改两处）。"""
    text = TS_PROTOCOL.read_text(encoding="utf-8")
    block = re.search(
        r"export const COMMANDS = \[(.*?)\] as const;", text, re.DOTALL)
    assert block is not None, "未找到 TS COMMANDS 数组"
    ts_cmds = tuple(re.findall(r'"([a-z_]+)"', block.group(1)))
    assert ts_cmds == tuple(browser_channel.COMMANDS), (
        f"两侧命令集不一致：TS={ts_cmds} PY={tuple(browser_channel.COMMANDS)}")


def test_protocol_version_parity_and_v4():
    """协议版本两侧对拍且 ≥4（v4：mode 第三值 storage-state + state_path）。"""
    text = TS_PROTOCOL.read_text(encoding="utf-8")
    m = re.search(r'export const PROTOCOL_VERSION = "([^"]+)";', text)
    assert m is not None, "未找到 TS PROTOCOL_VERSION"
    assert m.group(1) == browser_channel.PROTOCOL_VERSION
    assert int(browser_channel.PROTOCOL_VERSION) >= 4


def test_identity_clear_in_commands():
    assert "identity_clear" in browser_channel.COMMANDS
    assert "views" in browser_channel.COMMANDS


def test_channel_version_gate_fail_closed(monkeypatch):
    """旧通道（protocol<4）→ loud 拒结；status 自身不走门。"""
    client = ChannelClient("http://127.0.0.1:1", "t")
    monkeypatch.setattr(client, "_post",
                        lambda cmd, args, timeout: {"protocol": "3"})
    assert client.status() == {"protocol": "3"}
    with pytest.raises(browser_channel.BrowserChannelError) as ei:
        client.call("open", url="https://example.com")
    assert ei.value.code == "protocol-mismatch"


def test_channel_version_gate_passes_v4(monkeypatch):
    client = ChannelClient("http://127.0.0.1:1", "t")
    posts = []

    def fake_post(cmd, args, timeout):
        posts.append(cmd)
        return {"protocol": "4"} if cmd == "status" else {"title": "T"}

    monkeypatch.setattr(client, "_post", fake_post)
    assert client.call("open", url="x") == {"title": "T"}
    assert posts == ["status", "open"]
