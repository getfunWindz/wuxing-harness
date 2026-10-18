"""TDD · O2-2 P3 T5：浏览器允许条目 查看/撤销 API（设置「数据」运维面）。

设计 §11.3：`GET /api/v1/browser/allow`；`POST /api/v1/browser/allow/revoke`
（address+fingerprint 撤销，原子写回；缺失/损坏 → 空表 fail-closed 口径不变）。
"""
import http.client
import json

from wuxing import browser_guard
from wuxing.shell.web.hub import EventHub


class _FakeEngine:
    def __init__(self, workdir, auto_confirm=False):
        self.workdir = workdir


def _mk_server(tmp_path):
    from wuxing.shell.web.api import register_api
    from wuxing.shell.web.manager import EngineManager
    from wuxing.shell.web.server import ShellServer
    hub = EventHub()
    mgr = EngineManager(hub=hub, engine_factory=lambda w, a: _FakeEngine(w, a),
                        state_path=tmp_path / "ws.json")
    srv = ShellServer(port=0, hub=hub)
    register_api(srv, mgr)
    port = srv.start()
    return srv, port


def _request(port, method, path, body=None, mutate=False):
    headers = {"X-Wuxing": "1", "Content-Type": "application/json"} \
        if mutate else {}
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
    c.request(method, path,
              body=json.dumps(body) if body is not None else None,
              headers=headers)
    r = c.getresponse()
    raw = r.read()
    status = r.status
    c.close()
    return status, (json.loads(raw.decode("utf-8")) if raw else {})


def _patch_store(monkeypatch, tmp_path):
    store = tmp_path / "browser_allow.json"
    monkeypatch.setattr(browser_guard, "default_store_path", lambda: store)
    return store


_ENTRY = {"address": "127.0.0.1:8899",
          "occupant": {"pid": 1, "exe": "python.exe",
                       "cmdline": "python -m http.server",
                       "label": "python.exe", "fingerprint": "fp-abc"},
          "reason": "核查本地页面",
          "first_approved_at": "2026-10-08 10:00:00",
          "last_confirmed_at": "2026-10-08 10:00:00",
          "last_seen_at": "2026-10-08 10:01:00"}


def test_allow_list_empty_when_missing(tmp_path, monkeypatch):
    _patch_store(monkeypatch, tmp_path)
    srv, port = _mk_server(tmp_path)
    try:
        status, data = _request(port, "GET", "/api/v1/browser/allow")
        assert status == 200 and data["entries"] == []
    finally:
        srv.stop()


def test_allow_list_fields_and_revoke(tmp_path, monkeypatch):
    store = _patch_store(monkeypatch, tmp_path)
    browser_guard.save_allow({"version": 1, "entries": [dict(_ENTRY)]},
                             store_path=store)
    srv, port = _mk_server(tmp_path)
    try:
        status, data = _request(port, "GET", "/api/v1/browser/allow")
        assert status == 200
        e = data["entries"][0]
        assert e["address"] == "127.0.0.1:8899"
        assert e["label"] == "python.exe"
        assert e["fingerprint"] == "fp-abc"
        assert e["reason"] == "核查本地页面"

        # 未命中 → removed=0（不报错）
        status, data = _request(port, "POST",
                                "/api/v1/browser/allow/revoke",
                                {"address": "127.0.0.1:1",
                                 "fingerprint": "nope"}, mutate=True)
        assert status == 200 and data["removed"] == 0
        assert len(browser_guard.load_allow(store_path=store)["entries"]) == 1

        # 命中 → 移除 + 原子写回
        status, data = _request(port, "POST",
                                "/api/v1/browser/allow/revoke",
                                {"address": "127.0.0.1:8899",
                                 "fingerprint": "fp-abc"}, mutate=True)
        assert status == 200 and data["removed"] == 1
        assert browser_guard.load_allow(store_path=store)["entries"] == []
    finally:
        srv.stop()


def test_allow_revoke_requires_params(tmp_path, monkeypatch):
    _patch_store(monkeypatch, tmp_path)
    srv, port = _mk_server(tmp_path)
    try:
        status, _ = _request(port, "POST", "/api/v1/browser/allow/revoke",
                             {"address": "x"}, mutate=True)
        assert status == 422
    finally:
        srv.stop()


def test_allow_list_corrupt_store_empty(tmp_path, monkeypatch):
    store = _patch_store(monkeypatch, tmp_path)
    store.write_text("{broken", encoding="utf-8")
    srv, port = _mk_server(tmp_path)
    try:
        status, data = _request(port, "GET", "/api/v1/browser/allow")
        assert status == 200 and data["entries"] == []
    finally:
        srv.stop()


# ---- O2-2 §11.5-③：条目 kind（LAN/回环）+ LAN 撤销 ----


_LAN_ENTRY = {"kind": "lan", "address": "192.168.1.10:8000",
              "resolved_ips": ["192.168.1.10"],
              "occupant": {"pid": None, "exe": "", "cmdline": "",
                           "label": "局域网设备", "fingerprint": ""},
              "reason": "内网核查",
              "first_approved_at": "2026-10-13 10:00:00",
              "last_confirmed_at": "2026-10-13 10:00:00",
              "last_seen_at": "2026-10-13 10:01:00"}


def test_allow_list_kind_and_revoke_lan(tmp_path, monkeypatch):
    store = _patch_store(monkeypatch, tmp_path)
    browser_guard.save_allow(
        {"version": 1, "entries": [dict(_ENTRY), dict(_LAN_ENTRY)]},
        store_path=store)
    srv, port = _mk_server(tmp_path)
    try:
        status, data = _request(port, "GET", "/api/v1/browser/allow")
        assert status == 200
        by_kind = {e["kind"]: e for e in data["entries"]}
        assert by_kind["loopback"]["kind"] == "loopback"
        assert by_kind["lan"]["kind"] == "lan"
        assert by_kind["lan"]["resolved_ips"] == ["192.168.1.10"]
        status, out = _request(
            port, "POST", "/api/v1/browser/allow/revoke",
            {"address": "192.168.1.10:8000", "kind": "lan"}, mutate=True)
        assert status == 200 and out["removed"] == 1
        entries = browser_guard.load_allow(store_path=store)["entries"]
        assert [str(e.get("address")) for e in entries] == ["127.0.0.1:8899"]
        # 回环条目仍需 fingerprint（旧契约不弱化）
        status, _ = _request(port, "POST", "/api/v1/browser/allow/revoke",
                             {"address": "127.0.0.1:8899"}, mutate=True)
        assert status == 422
    finally:
        srv.stop()
