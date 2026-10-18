"""浏览器身份（O2-2 §11.5-①）：键/模式/注册表读取（中性模块——不触碰 Electron）。

设计：docs/WUXING_浏览器身份基线_设计_2026-10-08.md
  - 键 = `wuxing-browser-<sha1(normcase(realpath(ws_root)))[:16]>`（partition 基名）；
  - 模式：memory（默认；非 persist partition，退出即清）/ persist（跨重启）；
  - 注册表（Electron 单写）：`~/.wuxing/browser_identities.json`——仅 persist 条目；
    本模块只读（fail-closed：缺失/损坏=空表+注记）。
"""
import hashlib
import json
import logging
import os
import pathlib

from wuxing.atomic_write import read_text_retry

MODES = ("memory", "persist", "storage-state")
DEFAULT_MODE = "memory"
KEY_PREFIX = "wuxing-browser-"
MAX_STATE_BYTES = 2 * 1024 * 1024   # §11.5-③ D7：storage-state 文件上限

logger = logging.getLogger(__name__)


def identity_key(ws_root) -> str:
    """工作区 → 身份基键（规范化路径哈希；大小写/短路径安全）。"""
    norm = os.path.normcase(os.path.realpath(str(ws_root)))
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]
    return f"{KEY_PREFIX}{digest}"


def session_token(session) -> str:
    """会话名 → overlay 短码（8 hex；空会话=空串——headless/测试零变化）。"""
    name = str(session or "").strip()
    if not name:
        return ""
    norm = os.path.normcase(name)
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:8]


def anchor_of(ws_root) -> str:
    """真实工作区锚点：manifest_root 优先（E3-1/R5 状态根分离——
    worktree 隔离 run 的 manifest_root = 主工作区，身份不再随临时路径漂移）。

    注意：pathlib.Path 自带 `.root` 属性（盘符根），必须优先按纯路径处理。
    """
    if isinstance(ws_root, pathlib.PurePath):
        return str(ws_root)
    anchor = getattr(ws_root, "manifest_root", None)
    if anchor:
        return str(anchor)
    root = getattr(ws_root, "root", None)
    if root is not None:
        return str(root)
    return str(ws_root)


def resolve_mode(cfg) -> str:
    """配置 → 模式；非法值 fail-closed 到 memory（loud 告警，不静默持久化）。"""
    raw = str(getattr(cfg, "browser_identity_mode", "") or "").strip().lower()
    if raw in MODES:
        return raw
    if raw:
        logger.warning("browser_identity_mode 非法（%r）——按 memory 处理", raw)
    return DEFAULT_MODE


# ---- §11.5-③ storage-state（登录态档：只读注入；值纪律——只计数不返回值）----


def _state_token(path: pathlib.Path) -> str:
    """状态文件短码（mtime+size——内容变即换键，无需重读内容）。"""
    st = path.stat()
    raw = f"{path}|{st.st_size}|{st.st_mtime_ns}".encode()
    return hashlib.sha1(raw).hexdigest()[:8]


def _read_storage_state(cfg) -> dict:
    """→ {path, valid, cookies, origins, error}（值纪律：只计数不返回值）。"""
    raw_path = str(getattr(cfg, "browser_storage_state_path", "") or "").strip()
    out = {"path": raw_path, "valid": False, "cookies": 0, "origins": 0,
           "error": ""}
    if not raw_path:
        out["error"] = "storage-state 档未配置 browser_storage_state_path"
        return out
    path = pathlib.Path(raw_path)
    if not path.is_file():
        out["error"] = f"storage-state 文件不存在：{path}"
        return out
    try:
        if path.stat().st_size > MAX_STATE_BYTES:
            out["error"] = "storage-state 文件超限（>2MB）"
            return out
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        out["error"] = f"storage-state 文件读取失败：{exc}"
        return out
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        out["error"] = f"storage-state JSON 解析失败：{exc}"
        return out
    if not isinstance(data, dict):
        out["error"] = "storage-state 顶层必须是对象"
        return out
    cookies = data.get("cookies")
    origins = data.get("origins")
    if not isinstance(cookies, list) or not isinstance(origins, list):
        out["error"] = "storage-state 需要 cookies/origins 数组（Playwright 格式）"
        return out
    if not cookies and not origins:
        out["error"] = "storage-state 为空（无 cookies/origins）"
        return out
    out.update({"valid": True, "cookies": len(cookies),
                "origins": len(origins)})
    return out


def storage_state_summary(cfg) -> dict:
    """运维面摘要（设置 UI/API）：{path, valid, cookies, origins, error[, token]}。"""
    meta = _read_storage_state(cfg)
    if meta["valid"] and meta["path"]:
        try:
            meta["token"] = _state_token(pathlib.Path(meta["path"]))
        except OSError as exc:
            meta.update({"valid": False,
                         "error": f"storage-state 状态短码失败：{exc}"})
    return meta


def identity_for(cfg, ws_root, session="") -> dict:
    """命令携带的身份：{key, mode, workspace[, state_path|state_error]}。

    Q1=B / Q2=A（2026-10-13 裁决）：memory 档键 = 基键 + 会话 overlay
    （同会话续写保身份；并行 run 必属不同会话 → 隔离）；persist 档键 = 基键
    （长期档案按工作区，忽略会话）。§11.5-③：storage-state 档键 =
    基键 + 会话 overlay + 状态短码（mtime+size 哈希——文件变→换键→重建重注入）。
    无会话 → 基键（旧行为零变化）。基键锚定真实工作区（`anchor_of`）。
    """
    anchor = anchor_of(ws_root)
    mode = resolve_mode(cfg)
    key = identity_key(anchor)
    payload = {"key": key, "mode": mode, "workspace": anchor}
    if mode == "memory":
        token = session_token(session)
        if token:
            key = f"{key}-{token}"
    elif mode == "storage-state":
        meta = _read_storage_state(cfg)
        if meta["valid"]:
            state8 = _state_token(pathlib.Path(meta["path"]))
            payload["state_path"] = meta["path"]
        else:
            # 非法 → 键仍稳定（幂等清理可用）；错误由工具面 loud 上报（不回退档位）
            state8 = hashlib.sha1(
                str(meta["path"]).encode("utf-8")).hexdigest()[:8]
            payload["state_error"] = meta["error"]
        sess = session_token(session)
        parts = [p for p in (sess, state8) if p]
        key = f"{key}-" + "-".join(parts)
    payload["key"] = key
    return payload


def registry_path() -> pathlib.Path:
    return pathlib.Path.home() / ".wuxing" / "browser_identities.json"


def read_registry() -> tuple:
    """注册表 → (entries, problems)。缺失=空；损坏=空+注记（fail-closed）。"""
    problems: list = []
    path = registry_path()
    if not path.exists():
        return [], problems
    raw = read_text_retry(path)
    if raw is None:
        problems.append(f"{path} 读取失败（重试耗尽，按空表处理）")
        return [], problems
    try:
        data = json.loads(raw)
    except Exception as exc:
        return [], [f"{path} 读取失败：{exc}"]
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return [], [f"{path} 缺少 entries 数组"]
    out: list = []
    for e in entries:
        if not isinstance(e, dict) or not str(e.get("key") or "").strip():
            continue
        out.append({
            "key": str(e.get("key")),
            "workspace": str(e.get("workspace") or ""),
            "mode": str(e.get("mode") or "persist"),
            "first_used_at": str(e.get("first_used_at") or ""),
            "last_used_at": str(e.get("last_used_at") or ""),
        })
    return out, problems
