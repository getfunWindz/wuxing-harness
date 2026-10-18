"""回环访问护栏（O2-2 P1 · 一级组件）——占用探测 / 占用者指纹 / 允许条目 / 待决决议。

设计 SSOT：`docs/WUXING_内置浏览器体验断言_设计_2026-10-07.md` §3.1/§3.2。
口径（安全否定优先）：
  - 探测：True=有监听 / False=明确无监听 / None=未知 → **fail-closed 走确认**；
  - 占用者识别失败 = 未识别 → **绝不自动放行**（允许条目 fingerprint 为空 → 永不命中）；
  - 条目键 = 地址 + 占用者指纹（换应用/换命令行 → 不命中 → 重新确认）；
  - 存储损坏/缺失 → 视为空表（fail-closed）。
所有副作用（probe/identify/落盘路径/时钟/trace）可注入——离线可测。
"""
import hashlib
import ipaddress
import json
import pathlib
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass

from wuxing.atomic_write import atomic_write_text

_PENDING: dict = {}


def reset_pending_for_tests() -> None:
    """清空待决登记（测试隔离用；生产不使用）。"""
    _PENDING.clear()


@dataclass
class Occupant:
    """占用者（尽力而为识别；识别失败应传 None 而非空对象）。"""

    pid: int | None
    exe: str
    cmdline: str
    label: str

    def fingerprint(self) -> str:
        raw = f"{self.exe}\n{self.cmdline}".encode("utf-8", errors="replace")
        return hashlib.sha256(raw).hexdigest()[:16]


@dataclass
class GuardDecision:
    kind: str                   # no_listener | allowed | confirm_required | lan_denied
    address: str
    occupant: Occupant | None = None
    pending_id: str = ""
    entry: dict | None = None
    note: str = ""
    source: str = "loopback"    # loopback | lan（§11.5-③ 文案/条目分型）


def _ts(now_value: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_value))


def probe_listener(host: str, port: int, timeout: float = 0.5) -> bool | None:
    """TCP 占用探测：True 有监听 / False 明确无 / None 未知（fail-closed）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except ConnectionRefusedError:
        # 明确无监听——无需确认
        return False
    except OSError:
        # 探测未知（超时等）——fail-closed 走确认
        return None


def _default_run(cmd: list[str], timeout: float = 5.0) -> tuple:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout, check=False)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except Exception:
        return 1, ""


def _identify_windows(port: int, run) -> Occupant | None:
    rc, out = run(["powershell", "-NoProfile", "-Command",
                   (f"(Get-NetTCPConnection -LocalPort {port} -State Listen "
                    f"-ErrorAction SilentlyContinue | Select-Object -First 1 "
                    f"-ExpandProperty OwningProcess)")])
    pid = None
    if rc == 0 and str(out).strip().isdigit():
        pid = int(str(out).strip())
    if pid is None:  # 回退 netstat -ano
        rc2, out2 = run(["netstat", "-ano"])
        if rc2 == 0:
            for line in str(out2).splitlines():
                if f":{port}" in line and "LISTENING" in line.upper():
                    parts = line.split()
                    if parts and parts[-1].isdigit():
                        pid = int(parts[-1])
                        break
    if pid is None:
        return None
    name, exe, cmdline = "", "", ""
    rc3, out3 = run(["powershell", "-NoProfile", "-Command",
                     (f'Get-CimInstance Win32_Process -Filter "ProcessId={pid}" '
                      f"| Select-Object ProcessId,Name,ExecutablePath,CommandLine "
                      f"| ConvertTo-Json -Compress")])
    if rc3 == 0 and str(out3).strip():
        try:
            data = json.loads(str(out3).strip())
            if isinstance(data, list):
                data = data[0] if data else {}
            name = str(data.get("Name") or "")
            exe = str(data.get("ExecutablePath") or "")
            cmdline = str(data.get("CommandLine") or "")
        except (json.JSONDecodeError, AttributeError):
            # 解析失败 → 继续回退 tasklist（识别失败=未识别）
            pass
    if name == "":  # 回退 tasklist（仅名字）
        rc4, out4 = run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])
        if rc4 == 0 and str(out4).strip().startswith('"'):
            name = str(out4).strip().split('","')[0].strip('"')
    label = name or (pathlib.PureWindowsPath(exe).name if exe else "")
    return Occupant(pid=pid, exe=exe, cmdline=cmdline,
                    label=label or f"PID {pid}")


def _identify_posix(port: int, run) -> Occupant | None:
    rc, out = run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpct"])
    pid: int | None = None
    name = ""
    if rc == 0:
        for line in str(out).splitlines():
            if line.startswith("p") and line[1:].isdigit():
                pid = int(line[1:])
            elif line.startswith("c") and not name:
                name = line[1:].strip()
    if pid is None:
        return None
    cmdline = ""
    rc2, out2 = run(["ps", "-p", str(pid), "-o", "command="])
    if rc2 == 0:
        cmdline = str(out2).strip()
    exe = cmdline.split(" ")[0] if cmdline else name
    label = name or (pathlib.PurePosixPath(exe).name if exe else "")
    return Occupant(pid=pid, exe=exe, cmdline=cmdline,
                    label=label or f"PID {pid}")


def identify_occupant(port: int, *, platform: str | None = None,
                      run=None) -> Occupant | None:
    """占用者识别（尽力而为）——任何失败返回 None（=未识别，绝不自动放行）。"""
    run = run or _default_run
    plat = (platform or sys.platform or "").lower()
    try:
        if plat.startswith("win"):
            return _identify_windows(port, run)
        return _identify_posix(port, run)
    except Exception:
        # 识别失败=未识别（fail-closed：绝不自动放行）
        return None


def default_store_path() -> pathlib.Path:
    return pathlib.Path.home() / ".wuxing" / "browser_allow.json"


def load_allow(*, store_path=None) -> dict:
    """读允许条目；缺失/损坏 → 空表（fail-closed）。"""
    path = pathlib.Path(store_path) if store_path else default_store_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            raise TypeError("bad shape")
        return data
    except (OSError, json.JSONDecodeError, TypeError):
        return {"version": 1, "entries": []}


def save_allow(data: dict, *, store_path=None) -> None:
    path = pathlib.Path(store_path) if store_path else default_store_path()
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1))


def _find_entry(entries: list, address: str, fingerprint: str,
                kind: str = "loopback") -> dict | None:
    """条目匹配（kind 分型：loopback 按指纹；lan 按地址）。

    旧文件无 kind 字段 → 按 loopback（零迁移）；lan 条目不参与指纹匹配。
    """
    if kind == "lan":
        for entry in entries:
            if (str(entry.get("kind") or "loopback") == "lan"
                    and entry.get("address") == address):
                return entry
        return None
    if fingerprint == "":
        return None  # 未识别永不命中
    for entry in entries:
        if str(entry.get("kind") or "loopback") != "loopback":
            continue
        occ = entry.get("occupant") or {}
        if entry.get("address") == address and \
                str(occ.get("fingerprint") or "") == fingerprint:
            return entry
    return None


_RFC1918 = (ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"))
_ULA = ipaddress.ip_network("fc00::/7")


def lan_allow_networks(entries) -> tuple:
    """CIDR 白名单校验（D3）：仅 RFC1918/ULA 子网；非法条目 loud 记错。

    返回 (networks, errors)；有任一错误或空表 → 调用方应整体硬拒（不部分放行）。
    """
    nets, errs = [], []
    for raw in (entries or ()):
        try:
            net = ipaddress.ip_network(str(raw), strict=False)
        except ValueError as exc:
            errs.append(f"{raw}: {exc}")
            continue
        pools = _RFC1918 if net.version == 4 else (_ULA,)
        if not any(net.subnet_of(pool) for pool in pools):
            errs.append(f"{raw}: 仅允许 RFC1918 / IPv6 ULA 子网")
            continue
        nets.append(net)
    return nets, errs


def _ip_in_networks(ip_text: str, nets: list) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        # 非法 IP 字面量 → 不匹配（调用方据此 fail-closed 拒绝）
        return False
    return any(ip in net for net in nets if net.version == ip.version)


def resolve_addrs(host: str) -> list:
    """全部解析地址（去重排序）；失败 → 空表（fail-closed）。"""
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
    except OSError:
        # 解析失败 → 空表（调用方按 fail-closed 拒绝）
        return []


def check_lan(host: str, port: int, *, lan_allow=(), reason: str = "",
              store_path=None, probe=None, resolve=None, trace=None,
              now=None) -> GuardDecision:
    """LAN 动态授权（§11.5-③ Q1=A）：白名单 CIDR → 解析全落白名单 → 探测 →
    条目（kind=lan）/首访确认（远程主机无占用者指纹——按地址匹配）。
    """
    probe_fn = probe or probe_listener
    now_fn = now or time.time
    address = f"{host}:{port}"

    def _trace(event: str, **fields) -> None:
        if trace is not None:
            try:
                trace(event, **fields)
            except Exception:
                # trace 回调失败不阻塞判定（审计尽力而为）
                pass

    nets, errs = lan_allow_networks(lan_allow)
    if errs or not nets:
        return GuardDecision(
            kind="lan_denied", address=address, source="lan",
            note=("browser_lan_allow 配置非法：" + "；".join(errs))
            if errs else "browser_lan_allow 为空（LAN 硬拒）")
    ips = list((resolve or resolve_addrs)(host))
    if not ips or any(not _ip_in_networks(ip, nets) for ip in ips):
        return GuardDecision(
            kind="lan_denied", address=address, source="lan",
            note=f"地址不在 browser_lan_allow 白名单：{host}"
                 + (f"（解析 {ips}）" if ips else "（解析失败）"))

    result = probe_fn(host, port)
    _trace("browser_lan_probe", address=address, resolved_ips=ips,
           result=("listening" if result is True else
                   "no_listener" if result is False else "unknown"))
    if result is False:
        return GuardDecision(kind="no_listener", address=address,
                             source="lan", note="该地址无应用监听")
    if result is None:
        return GuardDecision(
            kind="confirm_required", address=address, source="lan",
            pending_id=_register_pending(address, None, reason, now_fn,
                                         kind="lan", resolved_ips=ips),
            note="占用探测未知（fail-closed）——需确认")

    data = load_allow(store_path=store_path)
    entries = data.get("entries", [])
    hit = _find_entry(entries, address, "", kind="lan")
    if hit is not None:
        hit["last_seen_at"] = _ts(now_fn())
        data["entries"] = entries
        save_allow(data, store_path=store_path)
        _trace("browser_lan_allow_hit", address=address)
        return GuardDecision(kind="allowed", address=address, source="lan",
                             entry=hit, note="命中允许条目")
    _trace("browser_lan_allow_miss", address=address, resolved_ips=ips)
    return GuardDecision(
        kind="confirm_required", address=address, source="lan",
        pending_id=_register_pending(address, None, reason, now_fn,
                                     kind="lan", resolved_ips=ips),
        note="首访 LAN 地址——需确认")


def check_loopback(host: str, port: int, *, reason: str = "", store_path=None,
                   probe=None, identify=None, trace=None, now=None) -> GuardDecision:
    """回环动态授权（每次导航调用）：探测 → 指纹比对 → 放行/确认。"""
    probe_fn = probe or probe_listener
    identify_fn = identify or identify_occupant
    now_fn = now or time.time
    address = f"{host}:{port}"

    def _trace(event: str, **fields) -> None:
        if trace is not None:
            try:
                trace(event, **fields)
            except Exception:
                # trace 回调失败不阻塞判定（审计尽力而为）
                pass

    result = probe_fn(host, port)
    _trace("browser_loopback_probe", address=address,
           result=("listening" if result is True else
                   "no_listener" if result is False else "unknown"))
    if result is False:
        return GuardDecision(kind="no_listener", address=address,
                             note="该地址无应用监听")
    if result is None:
        pending_id = _register_pending(address, None, reason, now_fn)
        return GuardDecision(kind="confirm_required", address=address,
                             pending_id=pending_id,
                             note="占用探测未知（fail-closed）——需确认")

    occupant = identify_fn(port)
    fingerprint = occupant.fingerprint() if occupant is not None else ""
    data = load_allow(store_path=store_path)
    entries = data.get("entries", [])
    hit = _find_entry(entries, address, fingerprint)
    if hit is not None:
        hit["last_seen_at"] = _ts(now_fn())
        data["entries"] = entries
        save_allow(data, store_path=store_path)
        _trace("browser_allow_hit", address=address, occupant=hit["occupant"])
        return GuardDecision(kind="allowed", address=address, occupant=occupant,
                             entry=hit, note="命中允许条目")

    has_address = any(e.get("address") == address for e in entries)
    _trace("browser_allow_reconfirm" if has_address else "browser_allow_miss",
           address=address,
           occupant=(occupant.label if occupant is not None else None))
    pending_id = _register_pending(address, occupant, reason, now_fn)
    return GuardDecision(
        kind="confirm_required", address=address, occupant=occupant,
        pending_id=pending_id,
        note=("占用者与已批准条目不一致——重新确认" if has_address
              else "未识别占用者——需确认" if occupant is None
              else "新占用者——需确认"))


def _register_pending(address: str, occupant: Occupant | None, reason: str,
                      now_fn, kind: str = "loopback",
                      resolved_ips: list | None = None) -> str:
    pending_id = uuid.uuid4().hex
    _PENDING[pending_id] = {
        "address": address,
        "kind": str(kind or "loopback"),
        "resolved_ips": list(resolved_ips or []),
        "occupant": ({"pid": occupant.pid, "exe": occupant.exe,
                      "cmdline": occupant.cmdline, "label": occupant.label,
                      "fingerprint": occupant.fingerprint()}
                     if occupant is not None else None),
        "reason": str(reason or ""),
        "created_at": _ts(now_fn()),
    }
    return pending_id


def resolve_pending(pending_id: str, approved: bool, *, note: str = "",
                    store_path=None, trace=None, now=None) -> dict:
    """用户决议：允许 → 写入条目（地址+占用者指纹+缘由+时间）；拒绝 → 不写。"""
    now_fn = now or time.time

    def _trace(event: str, **fields) -> None:
        if trace is not None:
            try:
                trace(event, **fields)
            except Exception:
                # trace 回调失败不阻塞决议（审计尽力而为）
                pass

    pending = _PENDING.pop(str(pending_id or ""), None)
    if pending is None:
        return {"resolved": False, "reason": "unknown_pending"}
    out = {"resolved": True, "approved": bool(approved), "entry": None}
    if approved:
        pend_kind = str(pending.get("kind") or "loopback")
        ts = _ts(now_fn())
        if pend_kind == "lan":
            entry = {
                "kind": "lan",
                "address": pending["address"],
                "resolved_ips": list(pending.get("resolved_ips") or []),
                "occupant": {"pid": None, "exe": "", "cmdline": "",
                             "label": "局域网设备", "fingerprint": ""},
                "reason": "｜".join(x for x in (pending.get("reason", ""),
                                                str(note or "")) if x),
                "first_approved_at": ts,
                "last_confirmed_at": ts,
                "last_seen_at": ts,
            }
            data = load_allow(store_path=store_path)
            entries = data.get("entries", [])
            existing = _find_entry(entries, entry["address"], "", kind="lan")
            if existing is not None:
                existing.update({"reason": entry["reason"],
                                 "last_confirmed_at": ts})
                entry = existing
            else:
                entries.append(entry)
            data["entries"] = entries
            save_allow(data, store_path=store_path)
            out["entry"] = entry
            _trace("browser_access_decided", address=pending["address"],
                   approved=True, kind="lan", note=str(note or "")[:120])
            return out
        ts = _ts(now_fn())
        occupant = pending.get("occupant") or {}
        entry = {
            "kind": "loopback",
            "address": pending["address"],
            "occupant": {
                "pid": occupant.get("pid"),
                "exe": occupant.get("exe", ""),
                "cmdline": occupant.get("cmdline", ""),
                "label": occupant.get("label", "未识别"),
                "fingerprint": occupant.get("fingerprint", ""),
            },
            "reason": "｜".join(x for x in (pending.get("reason", ""),
                                            str(note or "")) if x),
            "first_approved_at": ts,
            "last_confirmed_at": ts,
            "last_seen_at": ts,
        }
        data = load_allow(store_path=store_path)
        entries = data.get("entries", [])
        fp = entry["occupant"]["fingerprint"]
        existing = _find_entry(entries, entry["address"], fp)
        if existing is not None:
            existing.update({"reason": entry["reason"],
                             "last_confirmed_at": ts})
            entry = existing
        else:
            entries.append(entry)
        data["entries"] = entries
        save_allow(data, store_path=store_path)
        out["entry"] = entry
    _trace("browser_access_decided", address=pending["address"],
           approved=bool(approved), kind=str(pending.get("kind") or "loopback"),
           note=str(note or "")[:120])
    return out


def confirm_payload(decision: GuardDecision, agent_reason: str = "") -> dict:
    """确认门载荷（A′：统一四要素文案；agent 缘由标为不可信）。"""
    from wuxing import confirm_copy
    occ = getattr(decision, "occupant", None)
    label = str(getattr(occ, "label", "") or "") if occ is not None else ""
    return confirm_copy.browser_access_view(
        address=str(decision.address),
        source=str(getattr(decision, "source", "loopback") or "loopback"),
        occupant_label=label,
        occupant_unknown=(occ is None
                          and str(getattr(decision, "kind", "")) == "confirm_required"),
        agent_reason=agent_reason)


_ALLOW_LABEL = "允许访问"


def parse_access_decision(answer) -> bool:
    """确认答复 → 是否批准（保守：仅认选项标签；歧义/缺失一律拒绝）。

    壳答复格式 = `Q1 {题面}：{选项值}`（stream.ts 提交拼装）——取**最后一个
    冒号后的末段**与「允许访问」精确比对：自由文本/题面注入/否定表述
    （如「不允许访问」）一律 fail-closed（绝不默认放行）。
    """
    text = str(answer or "").strip()
    cut = max(text.rfind("："), text.rfind(":"))
    if cut >= 0:
        text = text[cut + 1:].strip()
    return text == _ALLOW_LABEL
