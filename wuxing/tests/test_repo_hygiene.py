"""仓库推送卫生检查（用户裁决 2026-09-30）：纯函数 fixture 驱动 + 仓库级集成。

覆盖：污物路径模式 / 高置信密钥 / 超大文件 / 机器路径（告警）。
"""
from scripts.repo_hygiene import (
    find_junk_tracked,
    find_large_tracked,
    find_machine_paths,
    find_secrets,
)


def test_junk_flags_logs_caches_and_env():
    paths = [
        "a/b.log",
        "x/__pycache__/m.pyc",
        "vendored/node_modules/pkg/index.js",
        "web/dist/app.js",
        ".env",
        "Thumbs.db",
        "src/app.py",
        "docs/design.md",
    ]
    junk = find_junk_tracked(paths)
    for bad in ("a/b.log", "x/__pycache__/m.pyc",
                "vendored/node_modules/pkg/index.js", "web/dist/app.js",
                ".env", "Thumbs.db"):
        assert bad in junk, bad
    assert "src/app.py" not in junk
    assert "docs/design.md" not in junk


def test_junk_env_example_allowed():
    assert find_junk_tracked([".env.example", ".env.sample"]) == []


def test_junk_e2e_runtime_dirs_flagged():
    paths = [
        "e2e/shell/fake-ws/ws.json",
        "e2e/shell/.runtime/artifacts/x.log",
        "e2e/shell/picked-ws-123/ws.json",
        "e2e/shell/serve_fake.py",
    ]
    junk = find_junk_tracked(paths)
    for bad in paths[:3]:
        assert bad in junk, bad
    assert "e2e/shell/serve_fake.py" not in junk


def test_secrets_flags_high_confidence_only():
    # 拼接构造：避免本文件被 repo_hygiene 自身的密钥扫描误伤（不得手改回字面量）
    key = "sk-" + "a" * 24
    files = {"a.py": f"key = '{key}'\n"}
    hits = find_secrets(files)
    assert hits and hits[0][0] == "a.py"
    # 低置信（太短/演示）不报
    assert find_secrets({"b.py": "token = 'sk-1'\n"}) == []
    assert find_secrets(
        {"c.py": 'assert "sk-1" in text  # already-clean-scan\n'}) == []


def test_secrets_private_key_and_github_pat():
    pat = "github_pat_" + "11ABCDEFG0123456789_" + "abcdefghij"
    pem = "-----BEGIN RSA " + "PRIVATE KEY-----" + "\nMIIE...\n"
    files = {"k.pem": pem, "ci.yml": f"token: {pat}\n"}
    hits = {p: name for p, name, _ in find_secrets(files)}
    assert "k.pem" in hits and "ci.yml" in hits


def test_large_flagged_above_limit():
    items = [("big.bin", 2 * 1024 * 1024), ("ok.bin", 1024)]
    assert find_large_tracked(items, limit=1024 * 1024) == ["big.bin"]
    assert find_large_tracked([("x", 100)], limit=1024 * 1024) == []


def test_machine_paths_reported_not_failed():
    win = "C:" + "/Users/someone/work/x"
    win2 = "C:" + "\\Users\\someone\\x"
    files = {
        "doc.md": f"见 {win} 与 {win2}",
        "code.py": "print('hello')\n",
    }
    got = find_machine_paths(files)
    assert "doc.md" in got
    assert "code.py" not in got
