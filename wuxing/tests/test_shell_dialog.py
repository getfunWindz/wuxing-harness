"""TDD：系统原生对话框桥（R1-1/R2-1）。

- 端点：POST /api/v1/dialog/pick → {"paths": [...]}（运行器可注入——测试不弹真实对话框）
- 桥：tkinter 子进程命令构造 + 输出解析（monkeypatch subprocess.run）
- 失败可见：桥不可用 → 503（不静默）
"""
import http.client
import json

import pytest


class _Eng:
    def __init__(self, workdir, auto_confirm=False):
        self.workdir = workdir


def _mk_server(tmp_path, dialog_runner=None):
    from wuxing.shell.web.api import register_api
    from wuxing.shell.web.hub import EventHub
    from wuxing.shell.web.manager import EngineManager
    from wuxing.shell.web.server import ShellServer
    hub = EventHub()
    mgr = EngineManager(hub=hub, engine_factory=lambda wd, ac: _Eng(wd, ac),
                        state_path=tmp_path / "ws.json")
    srv = ShellServer(port=0, hub=hub)
    register_api(srv, mgr, dialog_runner=dialog_runner)
    return srv, srv.start(), mgr


def _req(port, method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
    headers = ({} if method == "GET"
               else {"X-Wuxing": "1", "Content-Type": "application/json"})
    c.request(method, path, body=body, headers=headers)
    r = c.getresponse()
    data = r.read()
    status = r.status
    c.close()
    return status, data


def test_dialog_endpoint_returns_paths(tmp_path):
    calls = []

    def runner(kind):
        calls.append(kind)
        return ["C:/pick/a.txt", "C:/pick/b.txt"]

    srv, port, mgr = _mk_server(tmp_path, runner)
    try:
        status, data = _req(port, "POST", "/api/v1/dialog/pick",
                            body=json.dumps({"kind": "files"}))
        assert status == 200, data
        assert json.loads(data)["paths"] == ["C:/pick/a.txt", "C:/pick/b.txt"]
        assert calls == ["files"]
    finally:
        srv.stop()
        mgr.shutdown()


def test_dialog_endpoint_unavailable_503(tmp_path):
    def runner(kind):
        raise RuntimeError("tkinter 不可用")

    srv, port, mgr = _mk_server(tmp_path, runner)
    try:
        status, data = _req(port, "POST", "/api/v1/dialog/pick",
                            body=json.dumps({"kind": "file"}))
        assert status == 503, data
    finally:
        srv.stop()
        mgr.shutdown()


def test_dialog_endpoint_invalid_kind_422(tmp_path):
    def runner(kind):
        raise ValueError("未知对话框类型：nope")

    srv, port, mgr = _mk_server(tmp_path, runner)
    try:
        status, data = _req(port, "POST", "/api/v1/dialog/pick",
                            body=json.dumps({"kind": "nope"}))
        assert status == 422, data
    finally:
        srv.stop()
        mgr.shutdown()


def test_native_dialog_pick_parses(monkeypatch):
    from wuxing.shell.web import native_dialog

    class _CP:
        stdout = "C:/a.txt\nC:/dir with space/b.md\n"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(native_dialog.subprocess, "run", lambda *a, **k: _CP())
    assert native_dialog.pick("files") == ["C:/a.txt", "C:/dir with space/b.md"]

    class _Empty:
        stdout = ""
        stderr = ""
        returncode = 0

    monkeypatch.setattr(native_dialog.subprocess, "run", lambda *a, **k: _Empty())
    assert native_dialog.pick("file") == []


def test_native_dialog_pick_failure_visible(monkeypatch):
    """黄金测试修复（2026-09-30）：对话框子进程失败不得静默返回空列表——

    旧实现丢弃 returncode/stderr → 用户选中后若子进程崩溃（tkinter/编码等），
    前端只能拿空路径 → 退回手输弹窗 =「已选文件夹无效」的根源之一。
    失败必须带原因上升（端点转 503，UI 可见）。
    """
    from wuxing.shell.web import native_dialog

    class _Down:
        stdout = ""
        stderr = "Traceback (most recent call last):\nRuntimeError: boom-dialog"
        returncode = 1

    monkeypatch.setattr(native_dialog.subprocess, "run", lambda *a, **k: _Down())
    with pytest.raises(RuntimeError) as ei:
        native_dialog.pick("directory")
    assert "boom-dialog" in str(ei.value), str(ei.value)


def test_native_dialog_unknown_kind():
    from wuxing.shell.web import native_dialog
    with pytest.raises(ValueError):
        native_dialog.pick("nope")
