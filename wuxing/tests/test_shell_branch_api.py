"""G1：壳端点——对话分支 + 血缘可见（设计 §7.4）。"""
import http.client
import json
import pathlib


class _FakeEngine:
    """仅实现分支端点所需面（引擎集成由 test_conversation_branch 覆盖）。"""

    def __init__(self, workdir, auto_confirm=False):
        self.workdir = pathlib.Path(workdir)
        self.fail = None
        self.calls = []

    def branch_conversation(self, source, from_round, mode="redo",
                            summary="mech", focus="", max_chars=2000):
        self.calls.append({"source": source, "from_round": from_round,
                           "mode": mode, "summary": summary, "focus": focus})
        if self.fail:
            raise ValueError(self.fail)
        return {"created": True, "session": "conversation-999.jsonl",
                "path": str(self.workdir / ".wuxing" / "conversation-999.jsonl"),
                "source": source, "from_round": from_round, "mode": mode,
                "summary_mode_requested": summary, "summary_mode": "mech",
                "summary": "被放弃路径小结", "prefix_rounds": max(0, from_round - 1),
                "abandoned_rounds": 1, "redo_text": "原文"}


def _mk_server(tmp_path):
    from wuxing.shell.web.api import register_api
    from wuxing.shell.web.hub import EventHub
    from wuxing.shell.web.manager import EngineManager
    from wuxing.shell.web.server import ShellServer
    hub = EventHub()
    engines = {}

    def _factory(workdir, auto_confirm):
        return engines.setdefault(str(workdir),
                                  _FakeEngine(workdir, auto_confirm))

    mgr = EngineManager(hub=hub, engine_factory=_factory,
                        state_path=tmp_path / "ws.json", max_concurrent=2)
    srv = ShellServer(port=0, hub=hub)
    register_api(srv, mgr)
    port = srv.start()
    return srv, port, engines


def _request(port, method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
    c.request(method, path, body=body,
              headers={"X-Wuxing": "1", "Content-Type": "application/json"})
    r = c.getresponse()
    data = r.read()
    status = r.status
    c.close()
    return status, data


def _post(port, path, payload):
    return _request(port, "POST", path, body=json.dumps(payload))


def _open_ws(port, wd):
    status, data = _post(port, "/api/v1/workspaces", {"path": str(wd)})
    assert status == 200, data
    return json.loads(data)["id"]


def test_branch_endpoint_ok(tmp_path):
    srv, port, engines = _mk_server(tmp_path)
    try:
        wd = tmp_path / "proj"
        wd.mkdir()
        ws_id = _open_ws(port, wd)
        status, data = _post(
            port, f"/api/v1/workspaces/{ws_id}/conversations/branch",
            {"session": "conversation-a.jsonl", "from_round": 3,
             "mode": "redo", "summary": "mech", "focus": ""})
        assert status == 200, data
        res = json.loads(data)
        assert res["session"] == "conversation-999.jsonl"
        assert res["redo_text"] == "原文"
        calls = next(iter(engines.values())).calls
        assert calls and calls[-1]["from_round"] == 3
    finally:
        srv.stop()


def test_branch_endpoint_422(tmp_path):
    srv, port, engines = _mk_server(tmp_path)
    try:
        wd = tmp_path / "proj"
        wd.mkdir()
        ws_id = _open_ws(port, wd)
        base = f"/api/v1/workspaces/{ws_id}/conversations/branch"
        # 非法会话名（路径穿越/内部文件）
        for bad in ("../x.jsonl", "trace.jsonl"):
            status, _ = _post(port, base, {"session": bad, "from_round": 1})
            assert status == 422, bad
        # from_round 非法
        status, _ = _post(port, base,
                          {"session": "conversation-a.jsonl",
                           "from_round": "x"})
        assert status == 422
        # 引擎侧 ValueError → _guard 422（先成功一次：创建引擎实例）
        status, _ = _post(port, base,
                          {"session": "conversation-a.jsonl",
                           "from_round": 1})
        assert status == 200
        eng = next(iter(engines.values()))
        eng.fail = "分支轮次越界：第 9 轮不存在"
        status, data = _post(port, base,
                             {"session": "conversation-a.jsonl",
                              "from_round": 9})
        assert status == 422 and "越界" in data.decode("utf-8")
    finally:
        srv.stop()


def test_sessions_list_lineage_and_internal_hidden(tmp_path):
    srv, port, _engines = _mk_server(tmp_path)
    try:
        wd = tmp_path / "proj"
        (wd / ".wuxing").mkdir(parents=True)
        (wd / ".wuxing" / "conversation-a.jsonl").write_text(
            json.dumps({"round": 1, "user_text": "第一轮", "artifacts": [],
                        "summary": "done", "ts": 1.0},
                       ensure_ascii=False) + "\n", encoding="utf-8")
        (wd / ".wuxing" / "branches.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in [
                {"conversation": "conversation-a.jsonl",
                 "source": "conversation-origin.jsonl", "from_round": 2,
                 "mode": "redo", "summary_mode": "mech", "ts": 2.0},
                {"conversation": "conversation-gone.jsonl",
                 "source": "conversation-a.jsonl", "from_round": 1,
                 "mode": "continue", "summary_mode": "llm", "ts": 3.0},
            ]) + "\n", encoding="utf-8")
        ws_id = _open_ws(port, wd)
        status, data = _request(port, "GET",
                                f"/api/v1/workspaces/{ws_id}/sessions")
        assert status == 200
        sessions = json.loads(data)["sessions"]
        names = [s["name"] for s in sessions]
        assert "branches.jsonl" not in names  # 内部文件隐藏
        a = next(s for s in sessions if s["name"] == "conversation-a.jsonl")
        assert a["branched_from"] == {
            "source": "conversation-origin.jsonl", "from_round": 2,
            "mode": "redo", "summary_mode": "mech"}
    finally:
        srv.stop()


def test_session_transcript_skips_branch_rows(tmp_path):
    srv, port, _engines = _mk_server(tmp_path)
    try:
        wd = tmp_path / "proj"
        (wd / ".wuxing").mkdir(parents=True)
        rows = [
            {"round": 1, "user_text": "第一轮", "artifacts": [], "summary": "done",
             "ts": 1.0},
            {"type": "branch", "source": "conversation-o.jsonl", "from_round": 1,
             "mode": "redo", "summary_mode": "mech", "summary": "小结", "ts": 2.0},
            {"round": 2, "user_text": "修正", "artifacts": [], "summary": "done",
             "ts": 3.0},
        ]
        (wd / ".wuxing" / "conversation-a.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8")
        ws_id = _open_ws(port, wd)
        status, data = _request(
            port, "GET",
            f"/api/v1/workspaces/{ws_id}/sessions/conversation-a.jsonl")
        assert status == 200
        out_rows = json.loads(data)["rows"]
        assert [r.get("round") for r in out_rows] == [1, 2]
        assert all(r.get("type") != "branch" for r in out_rows)
    finally:
        srv.stop()
