"""TDD：工作区域轮次/碎片会话/轨迹端点（只读聚合——壳服务层）。"""
import http.client
import json

from wuxing.shell.web.hub import EventHub


def _mk_server(tmp_path):
    from wuxing.shell.web.api import register_api
    from wuxing.shell.web.manager import EngineManager
    from wuxing.shell.web.server import ShellServer

    hub = EventHub()
    mgr = EngineManager(hub=hub, state_path=tmp_path / "ws.json")
    srv = ShellServer(port=0, hub=hub)
    register_api(srv, mgr)
    port = srv.start()
    return srv, port, mgr


def _request(port, method, path):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
    c.request(method, path)
    r = c.getresponse()
    data = r.read()
    status = r.status
    c.close()
    return status, data


def _w(p, name, rows):
    p.mkdir(parents=True, exist_ok=True)
    (p / name).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def _seed(wd):
    from wuxing.shell.web import session_view as sv

    wux = wd / ".wuxing"
    _w(wux, "conversation-1.jsonl", [
        {"round": 1, "user_text": "线性任务", "summary": "done", "ts": 100.0, "artifacts": []},
        {"round": 2, "user_text": "并行任务", "summary": "done", "ts": 200.0, "artifacts": []},
    ])
    _w(wux, "provenance.jsonl", [
        {"unit_id": "L-1", "task_hash": sv.task_hash8("线性任务"), "goal": "线性",
         "domain": "execute", "status": "ok", "artifacts": [], "ts": 90.0},
        {"unit_id": "P-a", "task_hash": sv.task_hash8("并行任务"), "goal": "分支A",
         "domain": "execute", "status": "ok", "artifacts": [], "ts": 150.0},
        {"unit_id": "P-b", "task_hash": sv.task_hash8("并行任务"), "goal": "分支B",
         "domain": "plan", "status": "ok", "artifacts": [], "ts": 160.0},
    ])
    _w(wux, "trace.jsonl", [
        {"ts": 80.0, "event": "unit_started", "unit_id": "L-1", "domain": "execute"},
        {"ts": 90.0, "event": "unit_done", "unit_id": "L-1", "domain": "execute", "status": "ok"},
        {"ts": 140.0, "event": "unit_started", "unit_id": "P-a", "domain": "execute"},
        {"ts": 145.0, "event": "unit_started", "unit_id": "P-b", "domain": "plan"},
        {"ts": 155.0, "event": "unit_done", "unit_id": "P-a", "domain": "execute", "status": "ok"},
        {"ts": 175.0, "event": "unit_done", "unit_id": "P-b", "domain": "plan", "status": "ok"},
    ])
    _w(wux / "sessions", "2-P-a.jsonl", [
        {"round": 0, "state": "seed", "status": "", "ts": 140.0,
         "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "任务"}]},
        {"round": 1, "state": "done", "status": "ok", "ts": 155.0, "messages": []},
    ])


def test_session_rounds_endpoint(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    ws = mgr.open_workspace(str(wd))
    try:
        _seed(wd)
        status, data = _request(
            port, "GET",
            f"/api/v1/workspaces/{ws['id']}/sessions/conversation-1.jsonl/rounds")
        body = json.loads(data)
        assert status == 200, data
        assert [r["round"] for r in body["rounds"]] == [1, 2]
        assert body["rounds"][0]["parallel"] is False
        assert body["rounds"][1]["parallel"] is True
        assert body["rounds"][1]["fragments"][0]["session_file"] == "2-P-a.jsonl"
    finally:
        srv.stop()


def test_unit_session_endpoint(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    ws = mgr.open_workspace(str(wd))
    try:
        _seed(wd)
        status, data = _request(
            port, "GET",
            f"/api/v1/workspaces/{ws['id']}/unit-sessions/P-a")
        body = json.loads(data)
        assert status == 200, data
        assert body["unit_id"] == "P-a"
        assert [g["state"] for g in body["groups"]] == ["seed", "done"]
        assert body["meta"]["goal"] == "分支A"
    finally:
        srv.stop()


def test_unit_session_endpoint_rejects_traversal(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    ws = mgr.open_workspace(str(wd))
    try:
        _seed(wd)
        status, _ = _request(
            port, "GET",
            f"/api/v1/workspaces/{ws['id']}/unit-sessions/..%2Fsecrets")
        assert status == 404
    finally:
        srv.stop()


def test_trajectory_endpoint(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    ws = mgr.open_workspace(str(wd))
    try:
        _seed(wd)
        status, data = _request(
            port, "GET", f"/api/v1/workspaces/{ws['id']}/trajectory")
        body = json.loads(data)
        assert status == 200, data
        assert [r["round"] for r in body["rounds"]] == [1, 2]
        assert body["rounds"][0]["session"] == "conversation-1.jsonl"
        assert body["sessions"] == ["conversation-1.jsonl"]
    finally:
        srv.stop()
