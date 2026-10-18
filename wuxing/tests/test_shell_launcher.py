"""TDD：壳入口（壳 P1 · B5）——serve 复用 / app 薄壳与 pywebview 回退。"""
import socket


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.60", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_probe_and_ensure_service_reuse(tmp_path):
    from wuxing.shell.web import launcher
    port = _free_port()
    mgr, srv = launcher.ensure_service(
        port=port, state_path_override=tmp_path / "ws.json")
    assert mgr is not None and srv is not None
    try:
        info = launcher.probe("127.0.0.60", port)
        assert info and info["status"] == "ok"
        assert launcher.probe("127.0.0.60", _free_port()) is None
        mgr2, srv2 = launcher.ensure_service(
            port=port, state_path_override=tmp_path / "ws.json")
        assert (mgr2, srv2) == (None, None), "已有健康实例必须复用"
    finally:
        srv.stop()
        mgr.shutdown()


def test_run_serve_reports_existing(tmp_path, capsys):
    from wuxing.shell.web import launcher
    port = _free_port()
    mgr, srv = launcher.ensure_service(
        port=port, state_path_override=tmp_path / "ws.json")
    try:
        rc = launcher.run_serve(port=port)
        out = capsys.readouterr().out
        assert rc == 0 and "已有服务" in out
    finally:
        srv.stop()
        mgr.shutdown()


def test_run_app_opens_existing_service(tmp_path):
    from wuxing.shell.web import launcher
    port = _free_port()
    mgr, srv = launcher.ensure_service(
        port=port, state_path_override=tmp_path / "ws.json")
    opened = []
    try:
        rc = launcher.run_app(port=port, opener=lambda url: opened.append(url))
        assert rc == 0 and opened == [f"http://127.0.0.60:{port}"]
    finally:
        srv.stop()
        mgr.shutdown()


def test_run_app_spawns_when_missing(monkeypatch):
    from wuxing.shell.web import launcher
    port = _free_port()
    spawned, opened = [], []
    monkeypatch.setattr(launcher, "launch_service_process",
                        lambda p: spawned.append(p))
    monkeypatch.setattr(launcher, "_wait_health", lambda *a, **k: True)
    rc = launcher.run_app(port=port, opener=lambda url: opened.append(url))
    assert rc == 0
    assert spawned == [port], "无服务时必须拉起独立服务进程（关窗不杀服务）"
    assert opened == [f"http://127.0.0.60:{port}"]


def test_run_app_timeout_when_service_unavailable(monkeypatch, capsys):
    from wuxing.shell.web import launcher
    port = _free_port()
    monkeypatch.setattr(launcher, "launch_service_process", lambda p: None)
    monkeypatch.setattr(launcher, "_wait_health", lambda *a, **k: False)
    rc = launcher.run_app(port=port, opener=lambda url: None)
    assert rc == 1 and "超时" in capsys.readouterr().out


def test_run_app_fallback_without_pywebview(tmp_path, monkeypatch, capsys):
    from wuxing.shell.web import launcher, window
    port = _free_port()
    mgr, srv = launcher.ensure_service(
        port=port, state_path_override=tmp_path / "ws.json")

    def _boom(url, title="x"):
        raise window.WindowUnavailable("pywebview 未安装")

    monkeypatch.setattr(window, "open_window", _boom)
    try:
        rc = launcher.run_app(port=port)
        out = capsys.readouterr().out
        assert rc == 0 and "浏览器" in out and str(port) in out
    finally:
        srv.stop()
        mgr.shutdown()


def test_run_web_opens_browser_with_existing_service(tmp_path, capsys):
    """默认入口（web）：复用已有服务 → 拉起浏览器，不拉 pywebview。"""
    from wuxing.shell.web import launcher
    port = _free_port()
    mgr, srv = launcher.ensure_service(
        port=port, state_path_override=tmp_path / "ws.json")
    opened = []
    try:
        rc = launcher.run_web(port=port, opener=lambda url: opened.append(url))
        out = capsys.readouterr().out
        assert rc == 0 and opened == [f"http://127.0.0.60:{port}"]
        assert "已在运行" in out and str(port) in out
    finally:
        srv.stop()
        mgr.shutdown()


def test_run_web_spawns_background_service_when_missing(monkeypatch, capsys):
    from wuxing.shell.web import launcher
    port = _free_port()
    spawned, opened = [], []
    monkeypatch.setattr(launcher, "launch_service_process",
                        lambda p: spawned.append(p))
    monkeypatch.setattr(launcher, "_wait_health", lambda *a, **k: True)
    rc = launcher.run_web(port=port, opener=lambda url: opened.append(url))
    out = capsys.readouterr().out
    assert rc == 0
    assert spawned == [port], "无服务时必须后台拉起独立服务进程"
    assert opened == [f"http://127.0.0.60:{port}"]
    assert "正在启动" in out, "冷启动耗时较长——必须给出等待提示（避免疑似无响应）"


def test_run_web_timeout_when_service_unavailable(monkeypatch, capsys):
    from wuxing.shell.web import launcher
    port = _free_port()
    monkeypatch.setattr(launcher, "launch_service_process", lambda p: None)
    monkeypatch.setattr(launcher, "_wait_health", lambda *a, **k: False)
    rc = launcher.run_web(port=port, opener=lambda url: None)
    assert rc == 1 and "超时" in capsys.readouterr().out


def test_cli_shell_dispatch(monkeypatch):
    import sys

    from wuxing import cli
    from wuxing.shell.web import launcher
    calls = []
    monkeypatch.setattr(
        launcher, "run_serve",
        lambda port=0, host=None: calls.append(("serve", port, host)) or 0)
    monkeypatch.setattr(launcher, "run_app",
                        lambda port=0: calls.append(("app", port)) or 0)
    monkeypatch.setattr(sys, "argv",
                        ["wuxing", "shell", "serve", "--port", "9999"])
    cli.main()
    monkeypatch.setattr(sys, "argv",
                        ["wuxing", "shell", "serve", "--port", "9999",
                         "--host", "0.0.0.0"])
    cli.main()
    monkeypatch.setattr(sys, "argv",
                        ["wuxing", "shell", "app", "--port", "9998"])
    cli.main()
    assert calls == [("serve", 9999, None), ("serve", 9999, "0.0.0.0"),
                     ("app", 9998)]


def test_cli_bare_defaults_to_web(monkeypatch):
    """短命令 `wuxing` → 确保后台服务并拉起浏览器网页（不再默认 pywebview）。"""
    import sys

    from wuxing import cli
    from wuxing.shell.web import launcher
    web_calls, app_calls = [], []
    monkeypatch.setattr(launcher, "run_web",
                        lambda **kw: web_calls.append(kw) or 0)
    monkeypatch.setattr(launcher, "run_app",
                        lambda **kw: app_calls.append(kw) or 0)
    monkeypatch.setattr(sys, "argv", ["wuxing"])
    assert cli.main() == 0
    assert web_calls == [{}], "无子命令必须落到浏览器承载入口"
    assert app_calls == [], "默认入口不得再拉 pywebview 路径"


def test_pyproject_exposes_console_script():
    """打包入口点（安装后短命令 `wuxing`）——pyproject 必需项守卫。"""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.scripts]" in text
    assert 'wuxing = "wuxing.cli:main"' in text


def test_remote_auth_token(monkeypatch):
    from wuxing.shell.web import launcher
    monkeypatch.delenv("WUXING_SHELL_TOKEN", raising=False)
    assert launcher.remote_auth_token("127.0.0.60") is None
    assert launcher.remote_auth_token("0.0.0.0") is None
    monkeypatch.setenv("WUXING_SHELL_TOKEN", "tok")
    assert launcher.remote_auth_token("0.0.0.0") == "tok"


def test_run_serve_remote_requires_token(monkeypatch, capsys):
    from wuxing.shell.web import launcher
    monkeypatch.delenv("WUXING_SHELL_TOKEN", raising=False)
    monkeypatch.setattr(launcher, "probe", lambda *a, **k: None)
    rc = launcher.run_serve(port=_free_port(), host="192.168.250.250")
    out = capsys.readouterr().out
    assert rc == 2 and "令牌" in out and "fail-closed" in out


def test_build_service_wires_auth_and_allowlists(tmp_path):
    from wuxing.shell.web import launcher
    mgr, srv = launcher.build_service(
        host="127.0.0.60", port=0, state_path_override=tmp_path / "ws.json",
        auth_token="tok", allow_hosts=["100.64.1.5"],
        allow_origins=["http://100.64.1.5:8723"])
    try:
        assert srv.auth is not None
        assert srv.host_allowed("100.64.1.5")
        assert "http://100.64.1.5:8723" in srv.allowed_origins()
    finally:
        mgr.shutdown()
