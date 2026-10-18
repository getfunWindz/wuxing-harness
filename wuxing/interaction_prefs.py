"""交互偏好（#2 Phase 1.5）：确认卡「特调面」v0 —— 两级本机存档/合并/校验。

- 用户级 `~/.wuxing/interaction.json` + 工作区级 `<ws>/.wuxing/interaction.json`
  （不读仓库根层）；工作区字段存在则覆盖用户级，否则回退（逐字段）。
- fail-closed：缺失=内置默认；损坏=空档 + problems 注记（不崩、不静默半启用）。
- 呈现级偏好：绝不影响确认放行判定（机制裁决不动摇）。
"""
import json
import pathlib

from wuxing.atomic_write import atomic_write_text, read_text_retry

_STORE_VERSION = 1
DEFAULTS: dict = {
    "confirm_verbosity": "standard",     # standard | concise
    "details_default_open": False,
    "remember_details_choice": True,
    "confirm_notify": False,             # T-2：确认门等待时系统通知（仅窗口隐藏时发送）
}
_VERBOSITY = ("standard", "concise")


def user_store_path() -> pathlib.Path:
    return pathlib.Path.home() / ".wuxing" / "interaction.json"


def workspace_store_path(ws_root) -> pathlib.Path:
    return pathlib.Path(ws_root) / ".wuxing" / "interaction.json"


def _read_store(path: pathlib.Path) -> tuple:
    """单层存档 → (prefs, problems)。缺失=空；损坏=空+注记。"""
    problems: list = []
    if not path.exists():
        return {}, problems
    raw = read_text_retry(path)
    if raw is None:
        return {}, [f"{path} 读取失败（重试耗尽，按空档处理）"]
    try:
        data = json.loads(raw)
    except Exception as exc:
        return {}, [f"{path} 读取失败：{exc}"]
    if not isinstance(data, dict):
        return {}, [f"{path} 格式非法（顶层非对象）"]
    prefs = data.get("prefs")
    if not isinstance(prefs, dict):
        return {}, [f"{path} 缺少 prefs 对象"]
    out: dict = {}
    for key, val in prefs.items():
        if key not in DEFAULTS:
            problems.append(f"{path}:{key} 未知字段（忽略）")
            continue
        errors = validate_values({key: val})
        if errors:
            problems.extend(f"{path}: {e}" for e in errors)
            continue
        out[key] = val
    return out, problems


def load_scopes(ws_root=None) -> dict:
    """两层原始值 + problems：{"user": {...}, "workspace": {...}, "problems": []}。"""
    user, pu = _read_store(user_store_path())
    if ws_root:
        workspace, pw = _read_store(workspace_store_path(ws_root))
    else:
        workspace, pw = {}, []
    return {"user": user, "workspace": workspace, "problems": pu + pw}


def _effective_with_sources(user: dict, ws: dict) -> tuple:
    """逐字段覆盖：workspace > user > 默认；返回 (values, sources)。"""
    values, sources = {}, {}
    for key, default in DEFAULTS.items():
        if key in ws:
            values[key], sources[key] = ws[key], "workspace"
        elif key in user:
            values[key], sources[key] = user[key], "user"
        else:
            values[key], sources[key] = default, "default"
    return values, sources


def load_effective(ws_root=None) -> dict:
    """渲染/装配侧用：{values, problems}（工作区缺失→仅用户层）。"""
    scopes = load_scopes(ws_root)
    values, _ = _effective_with_sources(scopes["user"], scopes["workspace"])
    return {"values": values, "problems": scopes["problems"]}


def all_effective(ws_root=None) -> dict:
    """设置面用（两层原值 + 生效值 + 来源 + problems）。"""
    scopes = load_scopes(ws_root)
    values, sources = _effective_with_sources(scopes["user"],
                                              scopes["workspace"])
    return {"user": scopes["user"], "workspace": scopes["workspace"],
            "effective": values, "sources": sources,
            "problems": scopes["problems"]}


def validate_values(values) -> list:
    """写入前校验 → 错误列表（空=通过）；None=删除字段（合法）。"""
    errors: list = []
    if not isinstance(values, dict):
        return ["values 必须为对象"]
    for key, val in values.items():
        if key not in DEFAULTS:
            errors.append(f"未知字段：{key}")
            continue
        if val is None:
            continue                      # None=删除字段（回退）
        if key == "confirm_verbosity":
            if val not in _VERBOSITY:
                errors.append(
                    f"confirm_verbosity 必须为 {'/'.join(_VERBOSITY)}")
        elif not isinstance(val, bool):
            errors.append(f"{key} 必须为布尔")
    return errors


def save_scope(scope: str, ws_root, values) -> tuple:
    """写单层存档（字段存在=写入；None=删除字段）→ (data, errors)。原子写。"""
    if scope not in ("user", "workspace"):
        return {}, [f"scope 非法：{scope}"]
    errors = validate_values(values)
    if errors:
        return {}, errors
    path = user_store_path() if scope == "user" else workspace_store_path(ws_root)
    data, _ = _read_store(path)
    for key, val in (values or {}).items():
        if val is None:
            data.pop(key, None)
        else:
            data[key] = val
    payload = {"version": _STORE_VERSION, "prefs": data}
    atomic_write_text(path,
                      json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows：POSIX 权限位不适用（尽力而为）
    return data, []
