"""域提示词（重大优化清单 #3）：用户面每域系统提示词自定义——存档/合并/校验。

职责边界（设计 §2/§3）：
  - 两层本机存档：用户级 `~/.wuxing/domain_prompts.json` + 工作区级
    `<ws>/.wuxing/domain_prompts.json`（不读仓库根 config——防「克隆即注入」）；
  - 双段：notes（覆盖内置 quality_notes，空=内置默认）/ addendum（追加段，空=不注入）；
  - 逐字段覆盖：工作区字段存在则覆盖用户级，否则回退；
  - fail-closed：缺失=内置默认；损坏=空档 + problems 注记（不崩、不静默半启用）；
  - pure（纯极简）跳过由调用侧（runner）决策——本模块只给数据与诊断。
"""
import json
import pathlib

from wuxing.atomic_write import atomic_write_text, read_text_retry
from wuxing.domains.defaults import DEFAULT_DOMAINS, DESIGN_DOMAIN

MAX_SEGMENT_CHARS = 2000
_STORE_VERSION = 1

# 设置面域顺序（plan/execute/verify/user/design）
DOMAIN_IDS: tuple = tuple(DEFAULT_DOMAINS) + (DESIGN_DOMAIN.domain_id,)


def user_store_path() -> pathlib.Path:
    return pathlib.Path.home() / ".wuxing" / "domain_prompts.json"


def workspace_store_path(ws_root) -> pathlib.Path:
    return pathlib.Path(ws_root) / ".wuxing" / "domain_prompts.json"


def _domain_def(domain_id: str):
    for d in list(DEFAULT_DOMAINS.values()) + [DESIGN_DOMAIN]:
        if d.domain_id == domain_id:
            return d
    return None


def domain_title(domain_id: str) -> str:
    d = _domain_def(domain_id)
    return str(d.title) if d is not None else str(domain_id)


def builtin_notes(domain_id: str) -> str:
    d = _domain_def(domain_id)
    return str(d.quality_notes or "") if d is not None else ""


def _read_store(path: pathlib.Path) -> tuple:
    """单层存档 → ({domain: {notes?, addendum?}}, problems)。缺失=空；损坏=空+注记。"""
    problems: list = []
    if not path.exists():
        return {}, problems  # 缺失=正常态（免重试退避——每单元装配热路径）
    raw = read_text_retry(path)
    if raw is None:
        problems.append(f"{path} 读取失败（重试耗尽，按空档处理）")
        return {}, problems
    try:
        data = json.loads(raw)
    except Exception as exc:  # 损坏 → fail-closed 空档 + 注记
        return {}, [f"{path} 读取失败：{exc}"]
    if not isinstance(data, dict):
        return {}, [f"{path} 格式非法（顶层非对象）"]
    domains = data.get("domains")
    if not isinstance(domains, dict):
        return {}, [f"{path} 缺少 domains 对象"]
    out: dict = {}
    for did, entry in domains.items():
        if not isinstance(entry, dict):
            problems.append(f"{path}:{did} 条目非法（非对象）")
            continue
        if did not in DOMAIN_IDS:
            problems.append(f"{path}:{did} 未知域（忽略）")
            continue
        seg = {}
        for key in ("notes", "addendum"):
            val = entry.get(key)
            if isinstance(val, str) and val.strip():
                if len(val) > MAX_SEGMENT_CHARS:
                    problems.append(
                        f"{path}:{did}.{key} 超长"
                        f"（{len(val)}>{MAX_SEGMENT_CHARS}，忽略）")
                    continue
                seg[key] = val
        if seg:
            out[did] = seg
    return out, problems


def load_scopes(ws_root=None) -> dict:
    """两层原始值 + problems：{"user": {...}, "workspace": {...}, "problems": [...]}。

    ws_root 缺省/None → 工作区层为空（无工作区场景）。
    """
    user, pu = _read_store(user_store_path())
    if ws_root:
        workspace, pw = _read_store(workspace_store_path(ws_root))
    else:
        workspace, pw = {}, []
    return {"user": user, "workspace": workspace, "problems": pu + pw}


def _effective_pair(user_seg: dict, ws_seg: dict) -> dict:
    """逐字段覆盖：workspace 存在覆盖 user，否则回退 user；全缺=默认/none。"""
    notes, notes_src = "", "default"
    addendum, addendum_src = "", "none"
    if user_seg.get("notes"):
        notes, notes_src = user_seg["notes"], "user"
    if user_seg.get("addendum"):
        addendum, addendum_src = user_seg["addendum"], "user"
    if ws_seg.get("notes"):
        notes, notes_src = ws_seg["notes"], "workspace"
    if ws_seg.get("addendum"):
        addendum, addendum_src = ws_seg["addendum"], "workspace"
    return {"notes": notes, "notes_source": notes_src,
            "addendum": addendum, "addendum_source": addendum_src}


def load_effective(ws_root, domain_id: str) -> dict:
    """单域生效值（装配侧用）：{notes, addendum, notes_source, addendum_source, problems}。

    空串 = 无覆盖（notes → 装配侧回退内置默认；addendum → 不注入）。
    """
    scopes = load_scopes(ws_root)
    pair = _effective_pair(scopes["user"].get(domain_id) or {},
                           scopes["workspace"].get(domain_id) or {})
    pair["problems"] = scopes["problems"]
    return pair


def all_effective(ws_root=None) -> tuple:
    """全域条目（设置面用）→ (entries, problems)。字段与 DTO 对齐。"""
    scopes = load_scopes(ws_root)
    entries = []
    for did in DOMAIN_IDS:
        user = scopes["user"].get(did) or {}
        ws = scopes["workspace"].get(did) or {}
        pair = _effective_pair(user, ws)
        entries.append({
            "domain": did, "title": domain_title(did),
            "builtin_notes": builtin_notes(did),
            "notes_user": user.get("notes") or "",
            "notes_workspace": ws.get("notes") or "",
            "notes_effective": pair["notes"],
            "notes_source": pair["notes_source"],
            "addendum_user": user.get("addendum") or "",
            "addendum_workspace": ws.get("addendum") or "",
            "addendum_effective": pair["addendum"],
            "addendum_source": pair["addendum_source"],
        })
    return entries, scopes["problems"]


def validate_values(values) -> list:
    """写入前校验 → 错误列表（空=通过）。"""
    errors: list = []
    if not isinstance(values, dict):
        return ["values 必须为对象"]
    for did, entry in values.items():
        if did not in DOMAIN_IDS:
            errors.append(f"未知域：{did}")
            continue
        if not isinstance(entry, dict):
            errors.append(f"{did} 条目必须为对象")
            continue
        for key in ("notes", "addendum"):
            val = entry.get(key)
            if val is None:
                continue
            if not isinstance(val, str):
                errors.append(f"{did}.{key} 必须为字符串")
            elif len(val) > MAX_SEGMENT_CHARS:
                errors.append(f"{did}.{key} 超长"
                              f"（{len(val)}>{MAX_SEGMENT_CHARS}）")
    return errors


def save_scope(scope: str, ws_root, values) -> tuple:
    """写单层存档（字段存在=写入；空串=删除字段回退）→ (data, errors)。

    只改 values 中出现的域/字段，其余保留（逐字段写）。原子写（tmp+replace）。
    """
    if scope not in ("user", "workspace"):
        return {}, [f"scope 非法：{scope}"]
    errors = validate_values(values)
    if errors:
        return {}, errors
    path = user_store_path() if scope == "user" else workspace_store_path(ws_root)
    data, _ = _read_store(path)
    for did, entry in (values or {}).items():
        seg = dict(data.get(did) or {})
        for key in ("notes", "addendum"):
            if key not in entry:
                continue
            val = entry.get(key) or ""
            if str(val).strip() == "":
                seg.pop(key, None)
            else:
                seg[key] = str(val)
        if seg:
            data[did] = seg
        else:
            data.pop(did, None)
    payload = {"version": _STORE_VERSION, "domains": data}
    atomic_write_text(path,
                      json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows：POSIX 权限位不适用（尽力而为）
    return data, []
