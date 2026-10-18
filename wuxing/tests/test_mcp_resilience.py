"""R3-2/T6：MCP 环境擦洗 + 退避重连（纯函数）。"""
from wuxing.tools.mcp_bridge import (
    BACKOFF_MAX_MS,
    MAX_ATTEMPTS,
    backoff_ms,
    scrub_env,
    should_unload,
)


def test_scrub_env_removes_secrets_and_wuxing_prefix():
    base = {
        "PATH": "/usr/bin", "HOME": "/home/u",
        "OPENAI_API_KEY": "sk-x", "DB_PASSWORD": "p", "MY_SECRET": "s",
        "GH_TOKEN": "t", "WUXING_PORT": "8723", "LANG": "zh_CN.UTF-8",
    }
    out = scrub_env(base)
    assert set(out) == {"PATH", "HOME", "LANG"}
    assert "sk-x" not in out.values()


def test_env_for_merges_declared_optin(monkeypatch):
    from wuxing.tools.mcp_bridge import McpServerConfig, _env_for
    monkeypatch.setenv("MCP_TOKEN", "declared-secret")
    monkeypatch.setenv("OTHER_KEY", "should-be-scrubbed")
    cfg = McpServerConfig(name="demo", command="x",
                          env={"TOKEN": "MCP_TOKEN"})
    out = _env_for(cfg)
    assert out["TOKEN"] == "declared-secret"      # 显式声明 opt-in
    assert "OTHER_KEY" not in out                 # 未声明的机密仍被擦洗
    assert "PATH" in out                          # stdio 启动必需


def test_backoff_curve_and_cap():
    assert backoff_ms(1) == 500
    assert backoff_ms(2) == 1000
    assert backoff_ms(3) == 2000
    assert backoff_ms(7) == 32000 - 2000  # 2**6 * 500 = 32000 → 封顶
    assert backoff_ms(7) == BACKOFF_MAX_MS
    assert backoff_ms(99) == BACKOFF_MAX_MS
    assert backoff_ms(0) == 500           # 容错：下限从 1 起


def test_should_unload_at_max_attempts():
    assert not should_unload(1)
    assert not should_unload(MAX_ATTEMPTS - 1)
    assert should_unload(MAX_ATTEMPTS)


def test_reconnect_budget_state_machine():
    """T6b：失败退避 → 未到时刻 gate=False → 成功重置 → 上限卸载。"""
    from wuxing.tools.mcp_bridge import ReconnectBudget
    clock = {"t": 100.0}
    b = ReconnectBudget(now=lambda: clock["t"])
    assert b.gate() is True
    assert b.on_failure() == 0.5          # 第一次失败 → 退避 500ms
    assert b.gate() is False
    clock["t"] += 0.5
    assert b.gate() is True
    b.on_success()
    assert b.attempts == 0
    for _ in range(MAX_ATTEMPTS):
        b.on_failure()
    assert b.unloaded is True
    assert b.gate() is False
