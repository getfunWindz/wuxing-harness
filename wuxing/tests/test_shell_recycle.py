"""TDD：回收站（壳 UI 重构 · 阶段 2.3）——归档/恢复/彻底删除 + 磁盘安全语义。

设计 §5.1：壳里的删除只清壳/引擎数据；磁盘上的用户产物永不自动删除；
彻底删除需显式 purge 且二次确认（API 层强制 purge=true）。
"""
import http.client
import json


class _Eng:
    def __init__(self, workdir, auto_confirm=False):
        self.workdir = workdir


def _mk_server(tmp_path):
    from wuxing.shell.web.api import register_api
    from wuxing.shell.web.hub import EventHub
    from wuxing.shell.web.manager import EngineManager
    from wuxing.shell.web.server import ShellServer
    from wuxing.shell.web.state import RecycleStore
    hub = EventHub()
    mgr = EngineManager(hub=hub, engine_factory=lambda wd, ac: _Eng(wd, ac),
                        state_path=tmp_path / "ws.json")
    recycle = RecycleStore(tmp_path / "recycle.json")
    srv = ShellServer(port=0, hub=hub)
    register_api(srv, mgr, recycle=recycle)
    return srv, srv.start(), mgr, recycle


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


def _mk_ws(tmp_path, mgr):
    wd = tmp_path / "proj"
    (wd / ".wuxing").mkdir(parents=True)
    (wd / "user-file.txt").write_text("用户文件", encoding="utf-8")
    (wd / ".wuxing" / "conversation_a.jsonl").write_text(
        '{"role": "user", "content": "你好"}\n', encoding="utf-8")
    return mgr.open_workspace(str(wd)), wd


def test_archive_workspace_keeps_disk_files_and_records_entry(tmp_path):
    srv, port, mgr, _rc = _mk_server(tmp_path)
    ws, wd = _mk_ws(tmp_path, mgr)
    try:
        status, data = _req(port, "POST",
                            f"/api/v1/workspaces/{ws['id']}/archive",
                            body=json.dumps({"state": "archived"}))
        assert status == 200, data
        entry = json.loads(data)
        assert entry["kind"] == "workspace" and entry["state"] == "archived"
        # 壳侧：已从活动列表移除
        status, data = _req(port, "GET", "/api/v1/workspaces")
        assert json.loads(data)["workspaces"] == []
        # 磁盘：用户文件与引擎数据都在（绝不删）
        assert (wd / "user-file.txt").is_file()
        assert (wd / ".wuxing" / "conversation_a.jsonl").is_file()
        # 回收站有记录
        status, data = _req(port, "GET", "/api/v1/recycle")
        assert len(json.loads(data)["entries"]) == 1
    finally:
        srv.stop()
        mgr.shutdown()


def test_restore_workspace(tmp_path):
    srv, port, mgr, _rc = _mk_server(tmp_path)
    ws, _wd = _mk_ws(tmp_path, mgr)
    try:
        _s, data = _req(port, "POST", f"/api/v1/workspaces/{ws['id']}/archive",
                        body=json.dumps({"state": "trashed"}))
        eid = json.loads(data)["id"]
        status, data = _req(port, "POST", f"/api/v1/recycle/{eid}/restore")
        assert status == 200, data
        status, data = _req(port, "GET", "/api/v1/workspaces")
        assert [w["id"] for w in json.loads(data)["workspaces"]] == [ws["id"]]
        status, data = _req(port, "GET", "/api/v1/recycle")
        assert json.loads(data)["entries"] == []
    finally:
        srv.stop()
        mgr.shutdown()


def test_archive_session_hides_from_active_list_but_keeps_file(tmp_path):
    srv, port, mgr, _rc = _mk_server(tmp_path)
    ws, wd = _mk_ws(tmp_path, mgr)
    try:
        status, data = _req(
            port, "POST",
            f"/api/v1/workspaces/{ws['id']}/sessions/conversation_a.jsonl/archive",
            body=json.dumps({"state": "archived"}))
        assert status == 200, data
        assert json.loads(data)["kind"] == "session"
        status, data = _req(port, "GET",
                            f"/api/v1/workspaces/{ws['id']}/sessions")
        assert json.loads(data)["sessions"] == []
        assert (wd / ".wuxing" / "conversation_a.jsonl").is_file()
    finally:
        srv.stop()
        mgr.shutdown()


def test_purge_requires_explicit_flag(tmp_path):
    srv, port, mgr, _rc = _mk_server(tmp_path)
    ws, _wd = _mk_ws(tmp_path, mgr)
    try:
        _s, data = _req(port, "POST", f"/api/v1/workspaces/{ws['id']}/archive",
                        body=json.dumps({"state": "trashed"}))
        eid = json.loads(data)["id"]
        status, _data = _req(port, "DELETE", f"/api/v1/recycle/{eid}")
        assert status == 422
    finally:
        srv.stop()
        mgr.shutdown()


def test_purge_session_deletes_engine_file(tmp_path):
    srv, port, mgr, _rc = _mk_server(tmp_path)
    ws, wd = _mk_ws(tmp_path, mgr)
    try:
        _s, data = _req(
            port, "POST",
            f"/api/v1/workspaces/{ws['id']}/sessions/conversation_a.jsonl/archive",
            body=json.dumps({"state": "trashed"}))
        eid = json.loads(data)["id"]
        status, _data = _req(port, "DELETE", f"/api/v1/recycle/{eid}?purge=true")
        assert status == 200
        assert not (wd / ".wuxing" / "conversation_a.jsonl").exists()
        assert (wd / "user-file.txt").is_file(), "用户文件绝不能被删"
    finally:
        srv.stop()
        mgr.shutdown()


def test_purge_workspace_keeps_disk_and_engine_data(tmp_path):
    srv, port, mgr, _rc = _mk_server(tmp_path)
    ws, wd = _mk_ws(tmp_path, mgr)
    try:
        _s, data = _req(port, "POST", f"/api/v1/workspaces/{ws['id']}/archive",
                        body=json.dumps({"state": "trashed"}))
        eid = json.loads(data)["id"]
        status, _data = _req(port, "DELETE", f"/api/v1/recycle/{eid}?purge=true")
        assert status == 200
        assert (wd / "user-file.txt").is_file()
        assert (wd / ".wuxing" / "conversation_a.jsonl").is_file()
    finally:
        srv.stop()
        mgr.shutdown()


def test_purge_workspace_with_engine_flag_clears_engine_data_only(tmp_path):
    srv, port, mgr, _rc = _mk_server(tmp_path)
    ws, wd = _mk_ws(tmp_path, mgr)
    try:
        _s, data = _req(port, "POST", f"/api/v1/workspaces/{ws['id']}/archive",
                        body=json.dumps({"state": "trashed"}))
        eid = json.loads(data)["id"]
        status, _data = _req(
            port, "DELETE", f"/api/v1/recycle/{eid}?purge=true&engine=true")
        assert status == 200
        assert (wd / "user-file.txt").is_file()
        assert not (wd / ".wuxing").exists(), "显式 engine=true 才清引擎数据"
    finally:
        srv.stop()
        mgr.shutdown()


def test_recycle_unknown_entry_404(tmp_path):
    srv, port, mgr, _rc = _mk_server(tmp_path)
    try:
        status, _data = _req(port, "POST", "/api/v1/recycle/nonexistent/restore")
        assert status == 404
    finally:
        srv.stop()
        mgr.shutdown()


def test_restore_workspace_preserves_identity(tmp_path):
    """归档→恢复必须完整回填身份：自定义名称 + 文件夹归属。

    真实应用复现（2026-09-15）：恢复后工作区名从自定义名回退为目录名，
    文件夹归属丢失——`h_recycle_restore` 未回填条目中已存的名称。
    """
    srv, port, mgr, _rc = _mk_server(tmp_path)
    ws, _wd = _mk_ws(tmp_path, mgr)
    try:
        mgr.open_workspace(ws["path"], name="自定义名")
        folder = mgr.create_folder("研究")
        mgr.set_workspace_folder(ws["id"], folder["id"])
        _s, data = _req(port, "POST", f"/api/v1/workspaces/{ws['id']}/archive",
                        body=json.dumps({"state": "archived"}))
        entry = json.loads(data)
        eid = entry["id"]
        assert entry["name"] == "自定义名"
        status, data = _req(port, "POST", f"/api/v1/recycle/{eid}/restore")
        assert status == 200, data
        status, data = _req(port, "GET", "/api/v1/workspaces")
        w = json.loads(data)["workspaces"][0]
        assert w["name"] == "自定义名", f"恢复后名称丢失：{w['name']}"
        assert w["folder"] == folder["id"], f"恢复后文件夹归属丢失：{w['folder']}"
    finally:
        srv.stop()
        mgr.shutdown()
