"""TDD · O2-2 P1：回环访问护栏（探测/指纹/条目/决议——安全一级组件）。

设计：docs/WUXING_内置浏览器体验断言_设计_2026-10-07.md §3.1/§3.2。
全部注入式（probe/identify/run/store 路径），离线可测。
"""
import json

import pytest

from wuxing import browser_guard as guard
from wuxing.browser_guard import Occupant


@pytest.fixture(autouse=True)
def _clean_pending():
    guard.reset_pending_for_tests()
    yield
    guard.reset_pending_for_tests()


def _occ(pid=100, exe="C:/app/node.exe", cmdline="node server.js"):
    return Occupant(pid=pid, exe=exe, cmdline=cmdline, label="node.exe")


class _Trace:
    def __init__(self):
        self.events = []

    def __call__(self, event, **fields):
        self.events.append((event, fields))

    def names(self):
        return [e[0] for e in self.events]


def test_probe_refused_is_no_listener(tmp_path):
    tr = _Trace()
    d = guard.check_loopback("127.0.0.1", 3000, probe=lambda h, p: False,
                             trace=tr, store_path=tmp_path / "allow.json")
    assert d.kind == "no_listener"
    assert d.pending_id == ""
    assert not (tmp_path / "allow.json").exists()
    assert "browser_loopback_probe" in tr.names()


def test_probe_unknown_fail_closed(tmp_path):
    d = guard.check_loopback("127.0.0.1", 3000, probe=lambda h, p: None,
                             store_path=tmp_path / "allow.json")
    assert d.kind == "confirm_required"
    assert d.pending_id
    assert "fail-closed" in d.note or "未知" in d.note


def test_occupied_no_entry_confirm_with_events(tmp_path):
    tr = _Trace()
    d = guard.check_loopback("127.0.0.1", 3000, probe=lambda h, p: True,
                             identify=lambda p: _occ(), trace=tr,
                             store_path=tmp_path / "allow.json")
    assert d.kind == "confirm_required"
    assert d.occupant is not None and d.occupant.label == "node.exe"
    assert d.pending_id
    assert "browser_allow_miss" in tr.names()


def test_entry_hit_allowed_and_last_seen_updated(tmp_path):
    store = tmp_path / "allow.json"
    occ = _occ()
    guard.save_allow({"version": 1, "entries": [{
        "address": "127.0.0.1:3000",
        "occupant": {"pid": 100, "exe": occ.exe, "cmdline": occ.cmdline,
                     "label": occ.label, "fingerprint": occ.fingerprint()},
        "reason": "test", "first_approved_at": "2026-10-07 10:00:00",
        "last_confirmed_at": "2026-10-07 10:00:00", "last_seen_at": "",
    }]}, store_path=store)
    tr = _Trace()
    d = guard.check_loopback("127.0.0.1", 3000, probe=lambda h, p: True,
                             identify=lambda p: occ, trace=tr, store_path=store,
                             now=lambda: 1_700_000_000)
    assert d.kind == "allowed"
    assert "browser_allow_hit" in tr.names()
    saved = json.loads(store.read_text(encoding="utf-8"))
    assert saved["entries"][0]["last_seen_at"] != ""


def test_fingerprint_change_triggers_reconfirm(tmp_path):
    store = tmp_path / "allow.json"
    guard.save_allow({"version": 1, "entries": [{
        "address": "127.0.0.1:3000",
        "occupant": {"pid": 1, "exe": "C:/old/old.exe", "cmdline": "old",
                     "label": "old.exe", "fingerprint": "deadbeefdeadbeef"},
        "reason": "old", "first_approved_at": "", "last_confirmed_at": "",
        "last_seen_at": "",
    }]}, store_path=store)
    tr = _Trace()
    d = guard.check_loopback("127.0.0.1", 3000, probe=lambda h, p: True,
                             identify=lambda p: _occ(), trace=tr, store_path=store)
    assert d.kind == "confirm_required"
    assert "browser_allow_reconfirm" in tr.names()


def test_unknown_occupant_never_auto_allowed(tmp_path):
    store = tmp_path / "allow.json"
    guard.save_allow({"version": 1, "entries": [{
        "address": "127.0.0.1:3000",
        "occupant": {"pid": 0, "exe": "", "cmdline": "", "label": "未识别",
                     "fingerprint": ""},
        "reason": "approved-unknown", "first_approved_at": "",
        "last_confirmed_at": "", "last_seen_at": "",
    }]}, store_path=store)
    d = guard.check_loopback("127.0.0.1", 3000, probe=lambda h, p: True,
                             identify=lambda p: None, store_path=store)
    assert d.kind == "confirm_required"


def test_resolve_approve_writes_entry(tmp_path):
    store = tmp_path / "allow.json"
    tr = _Trace()
    d = guard.check_loopback("127.0.0.1", 3000, reason="核查本地页面",
                             probe=lambda h, p: True, identify=lambda p: _occ(),
                             trace=tr, store_path=store)
    out = guard.resolve_pending(d.pending_id, True, note="用户点了允许",
                                store_path=store, trace=tr)
    assert out["resolved"] is True and out["approved"] is True
    saved = json.loads(store.read_text(encoding="utf-8"))
    entry = saved["entries"][0]
    assert entry["address"] == "127.0.0.1:3000"
    assert entry["occupant"]["fingerprint"] == _occ().fingerprint()
    assert "核查本地页面" in entry["reason"]
    assert entry["first_approved_at"] and entry["last_confirmed_at"]
    assert "browser_access_decided" in tr.names()


def test_resolve_deny_no_entry(tmp_path):
    store = tmp_path / "allow.json"
    d = guard.check_loopback("127.0.0.1", 3000, probe=lambda h, p: True,
                             identify=lambda p: _occ(), store_path=store)
    out = guard.resolve_pending(d.pending_id, False, store_path=store)
    assert out["resolved"] is True and out["approved"] is False
    assert not store.exists()


def test_corrupt_store_treated_empty(tmp_path):
    store = tmp_path / "allow.json"
    store.write_text("{not json", encoding="utf-8")
    data = guard.load_allow(store_path=store)
    assert data["entries"] == []
    d = guard.check_loopback("127.0.0.1", 3000, probe=lambda h, p: True,
                             identify=lambda p: _occ(), store_path=store)
    assert d.kind == "confirm_required"


def test_resolve_unknown_pending_idempotent(tmp_path):
    out = guard.resolve_pending("nope", True, store_path=tmp_path / "a.json")
    assert out["resolved"] is False
    assert out["reason"] == "unknown_pending"


def test_identify_occupant_windows_parse():
    def run(cmd, timeout=5.0):
        joined = " ".join(cmd)
        if "Get-NetTCPConnection" in joined:
            return 0, "4242\n"
        if "Get-CimInstance" in joined:
            return 0, json.dumps({
                "ProcessId": 4242, "Name": "node.exe",
                "ExecutablePath": "C:/Program Files/nodejs/node.exe",
                "CommandLine": "node server.js --port 3000",
            })
        return 1, ""

    occ = guard.identify_occupant(3000, platform="win32", run=run)
    assert occ is not None
    assert occ.pid == 4242
    assert occ.label == "node.exe"
    assert len(occ.fingerprint()) == 16


def test_identify_occupant_failure_returns_none():
    occ = guard.identify_occupant(3000, platform="win32",
                                  run=lambda cmd, timeout=5.0: (1, ""))
    assert occ is None


def test_fingerprint_changes_with_cmdline():
    a = _occ(cmdline="node a.js").fingerprint()
    b = _occ(cmdline="node b.js").fingerprint()
    assert a != b and len(a) == 16


def test_confirm_payload_plain_language(tmp_path):
    d = guard.check_loopback("127.0.0.1", 3000, probe=lambda h, p: True,
                             identify=lambda p: _occ(),
                             store_path=tmp_path / "allow.json")
    payload = guard.confirm_payload(d, agent_reason="核查登录页体验")
    assert "127.0.0.1:3000" in payload["title"]
    assert "node.exe" in payload["title"]
    assert payload["options"] == ["允许访问", "拒绝"]
    assert "未核实" in payload["title"] and "核查登录页体验" in payload["title"]
    assert "允许后" in payload["title"] and "拒绝后" in payload["title"]
    assert len(payload["title"]) <= 200


# ---- O2-2 §11.5-③：LAN 动态授权（Q1=A / D1-D4） ----


def test_lan_network_validation_only_private():
    nets, errs = guard.lan_allow_networks(
        ["192.168.1.0/24", "10.0.0.0/8", "fd00::/8"])
    assert errs == [] and len(nets) == 3
    _, errs2 = guard.lan_allow_networks(
        ["0.0.0.0/0", "8.8.8.0/24", "169.254.0.0/16", "127.0.0.0/8"])
    assert len(errs2) == 4
    _, errs3 = guard.lan_allow_networks(["not-a-cidr"])
    assert len(errs3) == 1


def test_check_lan_confirm_then_hit(tmp_path):
    store = tmp_path / "allow.json"

    def check(**kw):
        return guard.check_lan(
            "192.168.1.10", 8000, lan_allow=["192.168.1.0/24"],
            reason="内网核查", store_path=store,
            probe=lambda h, p: True,
            resolve=lambda h: ["192.168.1.10"], **kw)

    d = check()
    assert d.kind == "confirm_required" and d.pending_id
    assert d.source == "lan"
    out = guard.resolve_pending(d.pending_id, True, store_path=store)
    assert out["resolved"] and out["entry"]["kind"] == "lan"
    assert out["entry"]["resolved_ips"] == ["192.168.1.10"]
    assert check().kind == "allowed"
    # 拒绝不写条目（独立地址/存储验证）
    store2 = tmp_path / "allow2.json"

    def check2():
        return guard.check_lan(
            "192.168.1.11", 8000, lan_allow=["192.168.1.0/24"],
            store_path=store2, probe=lambda h, p: True,
            resolve=lambda h: ["192.168.1.11"])

    d2 = check2()
    guard.resolve_pending(d2.pending_id, False, store_path=store2)
    assert check2().kind == "confirm_required"


def test_check_lan_denied_outside_or_bad_config(tmp_path):
    store = tmp_path / "allow.json"
    d = guard.check_lan("192.168.9.9", 80, lan_allow=["192.168.1.0/24"],
                        store_path=store, probe=lambda h, p: True,
                        resolve=lambda h: ["192.168.9.9"])
    assert d.kind == "lan_denied" and "白名单" in d.note
    d2 = guard.check_lan("10.0.0.5", 80, lan_allow=["8.8.8.0/24"],
                         store_path=store, probe=lambda h, p: True,
                         resolve=lambda h: ["10.0.0.5"])
    assert d2.kind == "lan_denied" and "配置非法" in d2.note
    d3 = guard.check_lan("10.0.0.5", 80, lan_allow=[],
                         store_path=store, probe=lambda h, p: True,
                         resolve=lambda h: ["10.0.0.5"])
    assert d3.kind == "lan_denied"


def test_check_lan_name_resolution_fail_closed(tmp_path):
    base = {"lan_allow": ["192.168.1.0/24"],
            "store_path": tmp_path / "a.json",
            "probe": lambda h, p: True}
    assert guard.check_lan("nas.local", 80, resolve=lambda h: ["192.168.2.5"],
                           **base).kind == "lan_denied"
    assert guard.check_lan("nas.local", 80, resolve=lambda h: [],
                           **base).kind == "lan_denied"
    d = guard.check_lan("nas.local", 80, resolve=lambda h: ["192.168.1.7"],
                        **base)
    assert d.kind == "confirm_required"
    # 混合公网/私网解析：任一落白名单外 → 拒（不部分放行）
    assert guard.check_lan(
        "mix.local", 80, resolve=lambda h: ["192.168.1.7", "8.8.8.8"],
        **base).kind == "lan_denied"


def test_check_lan_no_listener_and_unknown(tmp_path):
    base = {"lan_allow": ["192.168.1.0/24"],
            "store_path": tmp_path / "a.json",
            "resolve": lambda h: ["192.168.1.10"]}
    d = guard.check_lan("192.168.1.10", 80, probe=lambda h, p: False,
                        **base)
    assert d.kind == "no_listener"
    d2 = guard.check_lan("192.168.1.10", 80, probe=lambda h, p: None,
                         **base)
    assert d2.kind == "confirm_required"


def test_lan_confirm_payload_mentions_intranet():
    d = guard.GuardDecision(kind="confirm_required",
                            address="192.168.1.10:80", source="lan")
    p = guard.confirm_payload(d, agent_reason="核查内网页面")
    assert "局域网" in p["title"] and "无鉴权" in p["title"]
    head = p["title"].split("（agent 说明：")[0]   # 仅机制文案（不含 agent 缘由）
    assert head.count("内网") <= 1, "LAN 机制文案不得重复赘词"
    assert "允许后" in p["title"] and "拒绝后" in p["title"]
    assert p["options"] == ["允许访问", "拒绝"]


def test_lan_and_loopback_entries_coexist(tmp_path):
    store = tmp_path / "allow.json"
    d = guard.check_lan("192.168.1.10", 80, lan_allow=["192.168.1.0/24"],
                        store_path=store, probe=lambda h, p: True,
                        resolve=lambda h: ["192.168.1.10"])
    guard.resolve_pending(d.pending_id, True, store_path=store)
    # 回环条目不受影响：LAN 条目不应命中回环查找（address 相同也不串）
    assert guard._find_entry(guard.load_allow(store_path=store)["entries"],
                             "192.168.1.10:80", "fp", kind="loopback") is None
    assert guard.check_lan("192.168.1.10", 80,
                           lan_allow=["192.168.1.0/24"], store_path=store,
                           probe=lambda h, p: True,
                           resolve=lambda h: ["192.168.1.10"]).kind == "allowed"
