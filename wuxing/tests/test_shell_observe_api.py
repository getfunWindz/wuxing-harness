"""TDD：观测端点（壳 UI 阶段 4 · T4.1/T4.3）。

- 溯源/日志读取：只读消费 workdir 文件（缺文件空表；损坏行跳过——容错）
- 事件日志：读壳侧 events.jsonl 尾部
- 缓存复验：POST bench/cache（子进程运行 cache_bench——壳不 import 引擎内部）
"""
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


def _request(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    status = r.status
    c.close()
    return status, data


def _mut(port, method, path, payload=None):
    return _request(port, method, path,
                    body=json.dumps(payload) if payload is not None else None,
                    headers={"X-Wuxing": "1",
                             "Content-Type": "application/json"})


def test_observe_provenance_and_trace_tolerant(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    ws = mgr.open_workspace(str(wd))
    try:
        # 缺文件 → 空表（不崩）
        status, data = _request(
            port, "GET", f"/api/v1/workspaces/{ws['id']}/observe/provenance")
        assert status == 200 and json.loads(data)["rows"] == []

        (wd / ".wuxing").mkdir()
        (wd / ".wuxing" / "provenance.jsonl").write_text(
            '{"unit_id": "F-1", "parent_id": "", "domain": "execute", "status": "ok"}\n'
            'BROKEN LINE\n'
            '{"unit_id": "F-2", "parent_id": "F-1", "domain": "verify", "status": "ok"}\n',
            encoding="utf-8")
        status, data = _request(
            port, "GET", f"/api/v1/workspaces/{ws['id']}/observe/provenance")
        rows = json.loads(data)["rows"]
        assert [r["unit_id"] for r in rows] == ["F-1", "F-2"], "损坏行必须跳过"

        (wd / ".wuxing" / "trace.jsonl").write_text(
            '{"event": "tool_call", "unit_id": "F-1", "name": "bash"}\n'
            '{"event": "unit_done", "unit_id": "F-2"}\n', encoding="utf-8")
        status, data = _request(
            port, "GET",
            f"/api/v1/workspaces/{ws['id']}/observe/trace?limit=10&unit=F-2")
        rows = json.loads(data)["rows"]
        assert len(rows) == 1 and rows[0]["unit_id"] == "F-2", rows
    finally:
        srv.stop()


def test_events_log_endpoint_reads_tail(tmp_path):
    srv, port, _mgr = _mk_server(tmp_path)
    try:
        (tmp_path / "events.jsonl").write_text(
            '{"type": "task_submitted", "seq": 1}\n'
            '{"type": "task_done", "seq": 2}\n', encoding="utf-8")
        status, data = _request(port, "GET", "/api/v1/events/log?tail=1")
        assert status == 200
        rows = json.loads(data)["rows"]
        assert len(rows) == 1 and rows[0]["type"] == "task_done"
    finally:
        srv.stop()


def test_bench_cache_endpoint_runs_subprocess(tmp_path, monkeypatch):
    import subprocess as sp

    class _Done:
        returncode = 0
        stdout = b'{"repeat": {"hit_rate": 1.0}}'
        stderr = b""

    def fake_run(*args, **kwargs):
        return _Done()

    monkeypatch.setattr(sp, "run", fake_run)
    srv, port, mgr = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    ws = mgr.open_workspace(str(wd))
    try:
        status, data = _mut(port, "POST",
                            f"/api/v1/workspaces/{ws['id']}/bench/cache")
        assert status == 200, data
        payload = json.loads(data)
        assert payload["ok"] is True
        assert payload["result"]["repeat"]["hit_rate"] == 1.0
    finally:
        srv.stop()


def test_workspace_files_listing(tmp_path):
    """阶段 5（⑧）：工作区文件浏览（参考文件选择器）——越界拒绝/隐藏目录跳过。"""
    srv, port, mgr = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    (wd / "docs").mkdir()
    (wd / "notes.md").write_text("x", encoding="utf-8")
    (wd / ".hidden").mkdir()
    ws = mgr.open_workspace(str(wd))
    try:
        status, data = _request(
            port, "GET", f"/api/v1/workspaces/{ws['id']}/files")
        assert status == 200, data
        payload = json.loads(data)
        assert [d["name"] for d in payload["dirs"]] == ["docs"]
        assert [f["name"] for f in payload["files"]] == ["notes.md"]
        # 进入子目录
        status, data = _request(
            port, "GET", f"/api/v1/workspaces/{ws['id']}/files?path=docs")
        assert status == 200 and json.loads(data)["path"] == "docs"
        # 越界拒绝
        status, _d = _request(
            port, "GET", f"/api/v1/workspaces/{ws['id']}/files?path=../")
        assert status in (403, 404)
    finally:
        srv.stop()


def test_session_free_rename_and_listing(tmp_path):
    """会话命名（2026-09-19 用户裁决）：自由改名（无后缀自动补 .jsonl）；内部 jsonl 不入列表。"""
    srv, port, mgr = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    ws = mgr.open_workspace(str(wd))
    base = wd / ".wuxing"
    base.mkdir()
    (base / "conversation-a.jsonl").write_text(
        '{"role":"user","content":"改名前"}\n', encoding="utf-8")
    (base / "provenance.jsonl").write_text("{}\n", encoding="utf-8")
    (base / "trace.jsonl").write_text("{}\n", encoding="utf-8")
    try:
        status, data = _request(
            port, "GET", f"/api/v1/workspaces/{ws['id']}/sessions")
        assert status == 200, data
        names = [s["name"] for s in json.loads(data)["sessions"]]
        assert names == ["conversation-a.jsonl"], names  # 内部 jsonl 排除
        # 自由改名（无后缀）→ 自动补 .jsonl 且仍可列出
        status, data = _mut(
            port, "PUT",
            f"/api/v1/workspaces/{ws['id']}/sessions/conversation-a.jsonl",
            {"name": "我的会话"})
        assert status == 200, data
        assert (base / "我的会话.jsonl").is_file()
        status, data = _request(
            port, "GET", f"/api/v1/workspaces/{ws['id']}/sessions")
        names = [s["name"] for s in json.loads(data)["sessions"]]
        assert names == ["我的会话.jsonl"], names
        # 带空格/中文/横线均可（不再限制合法字符）
        import urllib.parse
        status, data = _mut(
            port, "PUT",
            f"/api/v1/workspaces/{ws['id']}/sessions/"
            + urllib.parse.quote("我的会话.jsonl", safe=""),
            {"name": "Weekly report - v2"})
        assert status == 200, data
        assert (base / "Weekly report - v2.jsonl").is_file()
        # 路径穿越仍拒绝
        status, _d = _mut(
            port, "PUT",
            f"/api/v1/workspaces/{ws['id']}/sessions/"
            + urllib.parse.quote("Weekly report - v2.jsonl", safe=""),
            {"name": "../evil"})
        assert status == 422, status
        assert not (wd / "evil.jsonl").exists()
    finally:
        srv.stop()


def test_search_tasks_and_sessions(tmp_path):
    """全库搜索：任务文本（壳历史）+ 会话名称/首部内容（workdir 只读）。"""
    import urllib.parse
    srv, port, mgr = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    ws = mgr.open_workspace(str(wd))
    (tmp_path / "tasks.jsonl").write_text(
        json.dumps({"ws_id": ws["id"], "run_id": "r1",
                    "task_text": "写一份周报", "status": "done",
                    "started_at": 1.0}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (wd / ".wuxing").mkdir()
    (wd / ".wuxing" / "conversation-2026.jsonl").write_text(
        json.dumps({"role": "user", "content": "关于周报的讨论"},
                   ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        q = urllib.parse.quote("周报")
        status, data = _request(port, "GET", f"/api/v1/search?q={q}")
        assert status == 200, data
        payload = json.loads(data)
        assert payload["tasks"] and payload["tasks"][0]["run_id"] == "r1"
        assert payload["sessions"] and payload["sessions"][0]["name"] == "conversation-2026.jsonl"
        assert "周报" in payload["sessions"][0]["snippet"]
        # 空查询 → 空结果
        status, data = _request(port, "GET", "/api/v1/search?q=")
        assert json.loads(data) == {"tasks": [], "sessions": []}
    finally:
        srv.stop()


def test_search_window_widened(tmp_path):
    """放宽搜索窗口（2026-09-22，FTS 前置）：任务 >200 条与会话 >60 行均可命中。"""
    import urllib.parse
    srv, port, mgr = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    ws = mgr.open_workspace(str(wd))
    # 205 条任务历史：最旧一条（文件首行）匹配——旧窗口 limit=200 会漏掉
    rows = [json.dumps({"ws_id": ws["id"], "run_id": "r-deep",
                        "task_text": "深埋任务（窗口外）", "status": "done",
                        "started_at": 1.0}, ensure_ascii=False)]
    for i in range(204):
        rows.append(json.dumps({"ws_id": ws["id"], "run_id": f"r{i}",
                                "task_text": f"普通任务 {i}", "status": "done",
                                "started_at": float(i + 2)},
                               ensure_ascii=False))
    (tmp_path / "tasks.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    # 70 行会话：命中在第 70 行（旧窗口只扫前 60 行）
    (wd / ".wuxing").mkdir()
    lines = [json.dumps({"role": "user", "content": f"普通对话 {i}"},
                        ensure_ascii=False) for i in range(69)]
    lines.append(json.dumps({"role": "user", "content": "深埋会话内容"},
                            ensure_ascii=False))
    (wd / ".wuxing" / "conversation-deep.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    try:
        q = urllib.parse.quote("深埋")
        status, data = _request(port, "GET", f"/api/v1/search?q={q}")
        assert status == 200, data
        payload = json.loads(data)
        assert any(t["run_id"] == "r-deep" for t in payload["tasks"]), \
            "任务搜索必须覆盖 200 条窗口外的记录"
        assert any(s["name"] == "conversation-deep.jsonl"
                   for s in payload["sessions"]), \
            "会话搜索必须扫描全文（不止前 60 行）"
    finally:
        srv.stop()
