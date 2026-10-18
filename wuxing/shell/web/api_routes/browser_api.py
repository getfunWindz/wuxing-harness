"""浏览器允许条目 查看/撤销（O2-2 P3 §11.3）+ 身份查看/清除（§11.5-①）。

条目文件 `~/.wuxing/browser_allow.json`（browser_guard 存储）；身份档=memory|persist，
注册表 `~/.wuxing/browser_identities.json`（Electron 单写，本模块只读）。
"""
import re

from wuxing import browser_guard, browser_identity
from wuxing.browser_channel import BrowserChannelError, ChannelClient
from wuxing.config_contract import effective_config
from wuxing.shell.web.server import error_response, json_response

from .base import _guard


def _channel_client():
    """控制通道客户端（web 承载无通道 → None；测试可注入桩）。"""
    return ChannelClient.from_env()


def register(server, ctx) -> None:
    manager = ctx.manager
    @_guard
    def h_browser_allow_list(req):
        data = browser_guard.load_allow()
        entries = []
        for entry in data.get("entries", []):
            occ = entry.get("occupant") or {}
            entries.append({
                "address": str(entry.get("address") or ""),
                "label": str(occ.get("label") or ""),
                "fingerprint": str(occ.get("fingerprint") or ""),
                "exe": str(occ.get("exe") or ""),
                "reason": str(entry.get("reason") or ""),
                "first_approved_at": str(entry.get("first_approved_at") or ""),
                "last_confirmed_at": str(entry.get("last_confirmed_at") or ""),
                "last_seen_at": str(entry.get("last_seen_at") or ""),
                "kind": str(entry.get("kind") or "loopback"),
                "resolved_ips": [str(ip) for ip in
                                 (entry.get("resolved_ips") or [])],
            })
        return json_response({"entries": entries})

    @_guard
    def h_browser_allow_revoke(req):
        body = req.json() or {}
        address = str(body.get("address") or "").strip()
        fingerprint = str(body.get("fingerprint") or "").strip()
        kind = str(body.get("kind") or "loopback").strip() or "loopback"
        if address == "":
            return error_response(422, "invalid", "需要 address")
        if kind == "loopback" and fingerprint == "":
            return error_response(422, "invalid", "回环条目需要 address 与 fingerprint")
        data = browser_guard.load_allow()
        entries = data.get("entries", [])

        def _match(e: dict) -> bool:
            if str(e.get("address") or "") != address:
                return False
            ekind = str(e.get("kind") or "loopback")
            if ekind != kind:
                return False
            if kind == "loopback":
                return str((e.get("occupant") or {})
                           .get("fingerprint") or "") == fingerprint
            return True

        kept = [e for e in entries if not _match(e)]
        removed = len(entries) - len(kept)
        if removed:
            data["entries"] = kept
            browser_guard.save_allow(data)
        return json_response({"removed": removed})

    server.add_route("GET", r"^/api/v1/browser/allow$", h_browser_allow_list)
    server.add_route("POST", r"^/api/v1/browser/allow/revoke$",
                     h_browser_allow_revoke)

    def _ws_root(ws_id: str):
        if not ws_id:
            return None
        try:
            return manager.get_workspace(ws_id)["path"]
        except Exception:
            # 未知/已关闭工作区 → None（GET 退化为仅用户层）——可恢复语义
            return None

    @_guard
    def h_browser_identity_get(req):
        ws_id = str(req.query.get("ws") or "").strip()
        workdir = _ws_root(ws_id)
        mode = str(browser_identity.DEFAULT_MODE)
        values: dict = {}
        if workdir:
            try:
                values = dict(effective_config(workdir)["values"])
                mode = str(values.get("browser_identity_mode") or mode)
            except Exception:
                # 配置读取失败 → memory（fail-closed——不误报 persist/storage-state）
                mode = str(browser_identity.DEFAULT_MODE)
        storage_state = None
        if workdir and mode == "storage-state":
            class _Cfg:
                browser_storage_state_path = str(
                    values.get("browser_storage_state_path") or "")
            summary = browser_identity.storage_state_summary(_Cfg())
            storage_state = {
                "path": summary["path"], "valid": summary["valid"],
                "cookies": summary["cookies"], "origins": summary["origins"],
                "error": summary["error"],
            }
        entries, problems = browser_identity.read_registry()
        current_key = browser_identity.identity_key(workdir) if workdir else ""
        return json_response({"mode": mode, "current_key": current_key,
                              "entries": entries, "problems": problems,
                              "storage_state": storage_state})

    @_guard
    def h_browser_identity_clear(req):
        body = req.json() or {}
        key = str(body.get("key") or "").strip()
        if not re.fullmatch(r"[a-z0-9-]{1,64}", key):
            return error_response(422, "invalid", "key 非法")
        client = _channel_client()
        if client is None:
            return error_response(
                503, "no-channel",
                "内置浏览器仅桌面壳可用（当前 web 承载）——无法清除身份")
        try:
            client.call("identity_clear", key=key)
        except BrowserChannelError as exc:
            return error_response(502, "channel-error", str(exc))
        entries, problems = browser_identity.read_registry()
        return json_response({"removed_key": key, "entries": entries,
                              "problems": problems})

    server.add_route("GET", r"^/api/v1/browser/identity$",
                     h_browser_identity_get)
    server.add_route("POST", r"^/api/v1/browser/identity/clear$",
                     h_browser_identity_clear)
