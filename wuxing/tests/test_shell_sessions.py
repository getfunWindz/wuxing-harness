"""TDD：会话管理端点（壳 UI 重构 · 阶段 2.2）——重命名 / 导出（列表与历史已有）。

设计 §5.2：会话二级菜单 = 重命名 / 归档 / 导出 / 复制路径 / 删除（归档与删除走回收站 T2.3）。
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
    hub = EventHub()
    mgr = EngineManager(hub=hub, engine_factory=lambda wd, ac: _Eng(wd, ac),
                        state_path=tmp_path / "ws.json")
    srv = ShellServer(port=0, hub=hub)
    register_api(srv, mgr)
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


def _open_ws(tmp_path, mgr):
    wd = tmp_path / "proj"
    ses = wd / ".wuxing"
    ses.mkdir(parents=True)
    (ses / "conversation_a.jsonl").write_text(
        '{"role": "user", "content": "你好"}\n'
        '{"role": "assistant", "content": "好的"}\n', encoding="utf-8")
    return mgr.open_workspace(str(wd)), wd


def test_session_export_real_round_format(tmp_path):
    """2026-10-01 壳端复验 P2：真实会话行格式（round/user_text/artifacts/summary）
    必须可导出——旧实现只认 role/content → 实机会话导出空文档（『## 』）。"""
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open_ws(tmp_path, mgr)
    try:
        ses = wd / ".wuxing"
        (ses / "conversation_b.jsonl").write_text(
            json.dumps({"round": 1, "user_text": "把文件改两行", "artifacts": ["a.md"],
                        "summary": "done；交付物 a.md", "ts": 1.0}, ensure_ascii=False) + "\n",
            encoding="utf-8")
        status, data = _req(
            port, "GET",
            f"/api/v1/workspaces/{ws['id']}/sessions/conversation_b.jsonl/export?format=md")
        assert status == 200, data
        out = json.loads(data)
        assert "把文件改两行" in out["content"]
        assert "done" in out["content"]
        assert "a.md" in out["content"]
    finally:
        srv.stop()
        mgr.shutdown()


def test_session_export_filters_internal_and_prefers_reply(tmp_path):
    """Task A4（Wave-1）：导出 — .wuxing/ 内部产物不出现；结果优先模型总体回复。

    F-* 中间产物不入用户导出（用户裁决 2026-10-01）；reply（pi 式总体回复）
    优先于机械 summary 作为「结果」行。
    """
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open_ws(tmp_path, mgr)
    try:
        ses = wd / ".wuxing"
        (ses / "conversation_c.jsonl").write_text(
            json.dumps({"round": 1, "user_text": "做站点",
                        "artifacts": ["index.html",
                                      ".wuxing/reports/F-1-result.md"],
                        "summary": "done；交付物 index.html",
                        "reply": "总体回复：站点已完成", "ts": 1.0},
                       ensure_ascii=False) + "\n",
            encoding="utf-8")
        status, data = _req(
            port, "GET",
            f"/api/v1/workspaces/{ws['id']}/sessions/conversation_c.jsonl/export?format=md")
        assert status == 200, data
        content = json.loads(data)["content"]
        assert "总体回复：站点已完成" in content
        assert "done；交付物" not in content, "有 reply 时不应回退机械 summary"
        assert ".wuxing/reports/F-1-result.md" not in content
        assert "index.html" in content
    finally:
        srv.stop()
        mgr.shutdown()


def test_session_rename(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open_ws(tmp_path, mgr)
    try:
        status, data = _req(port, "PUT",
                            f"/api/v1/workspaces/{ws['id']}/sessions/conversation_a.jsonl",
                            body=json.dumps({"name": "conversation_renamed.jsonl"}))
        assert status == 200, data
        assert json.loads(data)["name"] == "conversation_renamed.jsonl"
        ses = wd / ".wuxing"
        assert (ses / "conversation_renamed.jsonl").is_file()
        assert not (ses / "conversation_a.jsonl").exists()
    finally:
        srv.stop()
        mgr.shutdown()


def test_session_rename_rejects_bad_name(tmp_path):
    """2026-09-19 命名自由化：仅拒空名/路径穿越；任意字符/扩展名均允许（自动补 .jsonl）。"""
    srv, port, mgr = _mk_server(tmp_path)
    ws, _ = _open_ws(tmp_path, mgr)
    try:
        for bad in ("", "../escape.jsonl", "conversation/sub.jsonl",
                    r"a\b.jsonl"):
            status, _data = _req(
                port, "PUT",
                f"/api/v1/workspaces/{ws['id']}/sessions/conversation_a.jsonl",
                body=json.dumps({"name": bad}))
            assert status == 422, bad
        # 自由命名（旧口径的「非法」名现在合法）
        status, _data = _req(
            port, "PUT",
            f"/api/v1/workspaces/{ws['id']}/sessions/conversation_a.jsonl",
            body=json.dumps({"name": "evil.txt"}))
        assert status == 200, status
    finally:
        srv.stop()
        mgr.shutdown()


def test_session_rename_conflict(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open_ws(tmp_path, mgr)
    (wd / ".wuxing" / "conversation_b.jsonl").write_text("{}\n", encoding="utf-8")
    try:
        status, _data = _req(
            port, "PUT",
            f"/api/v1/workspaces/{ws['id']}/sessions/conversation_a.jsonl",
            body=json.dumps({"name": "conversation_b.jsonl"}))
        assert status == 409
    finally:
        srv.stop()
        mgr.shutdown()


def test_session_list_exposes_path(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, _wd = _open_ws(tmp_path, mgr)
    try:
        status, data = _req(
            port, "GET", f"/api/v1/workspaces/{ws['id']}/sessions")
        assert status == 200
        sessions = json.loads(data)["sessions"]
        assert sessions and sessions[0]["path"].endswith("conversation_a.jsonl")
    finally:
        srv.stop()
        mgr.shutdown()


def test_session_export_markdown_and_json(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, _ = _open_ws(tmp_path, mgr)
    try:
        status, data = _req(
            port, "GET",
            f"/api/v1/workspaces/{ws['id']}/sessions/conversation_a.jsonl/export?format=md")
        assert status == 200, data
        out = json.loads(data)
        assert out["filename"].endswith(".md")
        assert "你好" in out["content"] and "好的" in out["content"]

        status, data = _req(
            port, "GET",
            f"/api/v1/workspaces/{ws['id']}/sessions/conversation_a.jsonl/export?format=json")
        assert status == 200
        rows = json.loads(json.loads(data)["content"])
        assert rows[0]["content"] == "你好"
    finally:
        srv.stop()
        mgr.shutdown()
