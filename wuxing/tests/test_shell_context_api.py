"""TDD：上下文预览/编辑端点（B 期）——GET 预览 / GET 列表 / POST 编辑。"""
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


def _request(port, method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=10)
    headers = {}
    if method != "GET":
        headers["X-Wuxing"] = "1"
        headers["Content-Type"] = "application/json"
    c.request(method, path,
              body=json.dumps(body) if body is not None else None,
              headers=headers)
    r = c.getresponse()
    data = r.read()
    status = r.status
    c.close()
    return status, data


def _seed(tmp_path, mgr):
    wd = tmp_path / "proj"
    wd.mkdir()
    ws = mgr.open_workspace(str(wd))
    wux = wd / ".wuxing"
    wux.mkdir()
    from wuxing.conversation import ConversationState
    st = ConversationState(wux / "conversation-1.jsonl")
    st.append_turn(1, "第一轮需求", ["a.py"], "完成1")
    st.append_turn(2, "第二轮需求", [], "完成2")
    return ws, wd


def test_context_preview_endpoint_and_list(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, _wd = _seed(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    try:
        status, data = _request(
            port, "GET", f"{base}/context-preview?session=conversation-1.jsonl")
        assert status == 200, data
        d = json.loads(data)
        assert d["available"] is True
        assert d["session"] == "conversation-1.jsonl"
        assert d["window"] > 0 and d["percent"] > 0
        assert d["segments"] and d["rounds"]
        assert [r["round"] for r in d["rounds"]] == [1, 2]
        assert any(s["key"] == "history" for s in d["segments"])
        # 列表（dock 行 %）
        status, data = _request(port, "GET", f"{base}/context-previews")
        assert status == 200, data
        items = json.loads(data)["items"]
        assert any(i["session"] == "conversation-1.jsonl" for i in items)
        # 缺参 → 422
        status, _ = _request(port, "GET", f"{base}/context-preview")
        assert status == 422
        # 不存在的会话 → available False（不造假）
        status, data = _request(
            port, "GET", f"{base}/context-preview?session=nope.jsonl")
        assert status == 200 and json.loads(data)["available"] is False
    finally:
        srv.stop()


def test_context_edit_omit_replace_flow(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _seed(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    conv = wd / ".wuxing" / "conversation-1.jsonl"
    before = conv.read_bytes()
    try:
        _s, data = _request(
            port, "GET", f"{base}/context-preview?session=conversation-1.jsonl")
        hist_before = {s["key"]: s for s in json.loads(data)["segments"]}[
            "history"]["chars"]
        # 省略第二轮
        status, data = _request(
            port, "POST", f"{base}/conversations/conversation-1.jsonl/context-edits",
            {"round": 2, "op": "omit"})
        assert status == 200, data
        payload = json.loads(data)
        assert payload["ok"] is True
        flags = {r["round"]: r for r in payload["preview"]["rounds"]}
        assert flags[2]["omitted"] is True
        hist_after = {s["key"]: s for s in payload["preview"]["segments"]}[
            "history"]["chars"]
        assert hist_after < hist_before
        # 会话日志零改写
        assert conv.read_bytes() == before
        assert (wd / ".wuxing" / "context-edits.jsonl").is_file()
        # 替换：缺 content → 422
        status, _ = _request(
            port, "POST", f"{base}/conversations/conversation-1.jsonl/context-edits",
            {"round": 1, "op": "replace"})
        assert status == 422
        # 替换：合法 → 预览字符变化
        status, data = _request(
            port, "POST", f"{base}/conversations/conversation-1.jsonl/context-edits",
            {"round": 1, "op": "replace", "content": "改写后的第一轮"})
        assert status == 200, data
        flags = {r["round"]: r for r in json.loads(data)["preview"]["rounds"]}
        assert flags[1]["replaced"] is True
        assert conv.read_bytes() == before
        # 非法 op / 非法会话名
        status, _ = _request(
            port, "POST", f"{base}/conversations/conversation-1.jsonl/context-edits",
            {"round": 1, "op": "explode"})
        assert status == 422
        status, _ = _request(
            port, "POST", f"{base}/conversations/provenance.jsonl/context-edits",
            {"round": 1, "op": "omit"})
        assert status == 422
    finally:
        srv.stop()


def test_context_edit_restore_flow(tmp_path):
    """G3：restore 回到原文（会话轮 + 碎片消息）——审计保真。"""
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _seed(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    conv = wd / ".wuxing" / "conversation-1.jsonl"
    before = conv.read_bytes()
    try:
        # 会话轮：省略 → 恢复
        status, data = _request(
            port, "POST",
            f"{base}/conversations/conversation-1.jsonl/context-edits",
            {"round": 2, "op": "omit"})
        assert status == 200
        flags = {r["round"]: r for r in json.loads(data)["preview"]["rounds"]}
        assert flags[2]["omitted"] is True
        status, data = _request(
            port, "POST",
            f"{base}/conversations/conversation-1.jsonl/context-edits",
            {"round": 2, "op": "restore"})
        assert status == 200, data
        flags = {r["round"]: r for r in json.loads(data)["preview"]["rounds"]}
        assert flags[2]["omitted"] is False
        # 审计保真：对话文件不变 + sidecar 保留 omit/restore 两行
        assert conv.read_bytes() == before
        rows = [json.loads(l) for l in
                (wd / ".wuxing" / "context-edits.jsonl").read_text(
                    encoding="utf-8").splitlines() if l.strip()]
        ops = [r["op"] for r in rows
               if r["conversation"] == "conversation-1.jsonl"]
        assert ops == ["omit", "restore"]
        # 碎片消息：restore 幂等 200；非法 op 422
        status, data = _request(
            port, "POST", f"{base}/unit-sessions/F-0001/context-edits",
            {"index": 0, "op": "restore", "fp_in": "x", "fp_out": "x"})
        assert status == 200, data
        status, _ = _request(
            port, "POST", f"{base}/unit-sessions/F-0001/context-edits",
            {"index": 0, "op": "explode"})
        assert status == 422
        # replace 缺 content 仍 422（回归）
        status, _ = _request(
            port, "POST",
            f"{base}/conversations/conversation-1.jsonl/context-edits",
            {"round": 1, "op": "replace"})
        assert status == 422
    finally:
        srv.stop()


def test_session_transcript_skips_compaction_rows(tmp_path):
    """G7：会话流不渲染压缩行；预览轮次带 compacted 标记。"""
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _seed(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    conv = wd / ".wuxing" / "conversation-1.jsonl"
    comp = {"type": "compaction", "from_round": 1, "to_round": 1,
            "summary": "COMPACT-XYZ", "mode": "llm", "ts": 5.0}
    conv.write_text(conv.read_text(encoding="utf-8")
                    + json.dumps(comp, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    try:
        status, data = _request(port, "GET",
                                f"{base}/sessions/conversation-1.jsonl")
        assert status == 200
        rows = json.loads(data)["rows"]
        assert all(str(r.get("type") or "") != "compaction" for r in rows)
        status, data = _request(
            port, "GET",
            f"{base}/context-preview?session=conversation-1.jsonl")
        assert status == 200
        flags = {r["round"]: r for r in json.loads(data)["rounds"]}
        assert flags[1]["compacted"] is True
        assert flags[2]["compacted"] is False
    finally:
        srv.stop()


def test_context_sources_endpoints(tmp_path):
    """A1：来源开关 GET/PUT（会话级持久）+ 投影同步 + 校验。"""
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _seed(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    try:
        status, data = _request(
            port, "GET", f"{base}/context-sources?session=conversation-1.jsonl")
        assert status == 200, data
        d = json.loads(data)
        assert d["ok"] is True and d["sources"]["history"] is True
        assert d["preview"]["sources"]["history"] is True
        # 关 history + 设预算 → 投影同步
        status, data = _request(
            port, "PUT", f"{base}/context-sources?session=conversation-1.jsonl",
            {"history": False, "budget_tokens": 5000})
        assert status == 200, data
        d = json.loads(data)
        assert d["sources"]["history"] is False
        assert d["sources"]["budget_tokens"] == 5000
        assert not any(s["key"] == "history" for s in d["preview"]["segments"])
        # 非法键 / 非法预算 / 缺参
        status, _ = _request(
            port, "PUT", f"{base}/context-sources?session=conversation-1.jsonl",
            {"nope": True})
        assert status == 422
        status, _ = _request(
            port, "PUT", f"{base}/context-sources?session=conversation-1.jsonl",
            {"budget_tokens": "x"})
        assert status == 422
        status, _ = _request(port, "GET", f"{base}/context-sources")
        assert status == 422
        # sidecar 落盘
        assert (wd / ".wuxing" / "context-sources.json").is_file()
    finally:
        srv.stop()


def test_unit_context_edit_endpoint(tmp_path):
    """A2：碎片消息三键编辑端点（omit → 投影前缀降/行标已省略；replace 缺 content 422）。"""
    import json as _json

    from wuxing.context_sources import content_fp
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _seed(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    sess = wd / ".wuxing" / "sessions"
    sess.mkdir(parents=True, exist_ok=True)
    (sess / "1-P-a.jsonl").write_text(
        _json.dumps({"round": 0, "state": "seed", "ts": 1.0,
                     "messages": [{"role": "user", "content": "碎片任务"}]},
                    ensure_ascii=False) + "\n"
        + _json.dumps({"round": 1, "state": "thinking", "ts": 2.0,
                       "messages": [{"role": "user", "content": "[tool] write: ok"}]},
                      ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        status, data = _request(
            port, "POST", f"{base}/unit-sessions/P-a/context-edits",
            {"index": 0, "fp_in": content_fp("碎片任务"), "fp_out": "",
             "op": "omit"})
        assert status == 200, data
        d = json.loads(data)
        assert d["ok"] is True
        assert d["preview"]["messages"][0]["omitted"] is True
        seg = {s["key"]: s for s in d["preview"]["segments"]}["fsc_prefix"]
        assert seg["chars"] == len("[tool] write: ok")
        # replace 缺 content → 422；非法 op → 422
        status, _ = _request(
            port, "POST", f"{base}/unit-sessions/P-a/context-edits",
            {"index": 1, "fp_in": content_fp("[tool] write: ok"),
             "fp_out": "", "op": "replace"})
        assert status == 422
        status, _ = _request(
            port, "POST", f"{base}/unit-sessions/P-a/context-edits",
            {"index": 1, "op": "explode"})
        assert status == 422
    finally:
        srv.stop()
