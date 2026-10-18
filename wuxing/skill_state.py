"""技能启停与固定状态（sidecar：~/.wuxing/state/skills/{disabled,pinned}.json；
旧 ~/.wuxing/skills-disabled.json / skills-pinned.json 兼容读）。

M7 挂账 #5（用户裁决 2026-09-20）：技能可停用——停用后不出现在
技能索引/选择器，`load_skill` 拒绝；状态为运行期用户状态（不进 config），
原子写落盘；测试经 conftest 全局隔离（`state_path`/`pinned_path` 可 monkeypatch）。

E2-1（item 11 · B5/H2）：新增 pinned（固定）侧车——pinned 技能豁免 curator
生命周期转换（stale/archive），语义与停用同类（运行期用户状态、原子写）。
P3（2026-10-18）：sidecar 收敛到 state/ 子目录；旧路径只读兼容。
"""
import json
import os
import pathlib

from wuxing.atomic_write import atomic_write_text


def state_dir() -> pathlib.Path:
    """P3：用户技能 sidecar 目录（~/.wuxing/state/skills）。"""
    return pathlib.Path(os.path.expanduser("~")) / ".wuxing" / "state" / "skills"


def state_path() -> pathlib.Path:
    """停用列表文件路径（测试可 monkeypatch——conftest 全局隔离）。"""
    return state_dir() / "disabled.json"


def pinned_path() -> pathlib.Path:
    """固定（pinned）技能清单文件路径（E2-1；测试可 monkeypatch）。"""
    return state_dir() / "pinned.json"


def legacy_state_path() -> pathlib.Path:
    """旧停用列表路径（P3 兼容读）。"""
    return pathlib.Path(os.path.expanduser("~")) / ".wuxing" / "skills-disabled.json"


def legacy_pinned_path() -> pathlib.Path:
    """旧固定清单路径（P3 兼容读）。"""
    return pathlib.Path(os.path.expanduser("~")) / ".wuxing" / "skills-pinned.json"


def _load_names(path: pathlib.Path) -> set:
    """读取名称集合（文件缺失/破损 → 空集，容错不阻塞）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    names = data.get("names") if isinstance(data, dict) else None
    if not isinstance(names, list):
        return set()
    return {str(n).strip() for n in names if str(n).strip()}


def _save_names(path: pathlib.Path, names) -> None:
    """原子写名称集合（排序去重，幂等）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps({"names": sorted(set(names))},
                                       ensure_ascii=False, indent=2))


def load_disabled() -> set:
    """读取停用技能名集合（新路径优先，旧路径兼容；缺失/破损 → 空集）。"""
    path = state_path()
    if path.exists():
        return _load_names(path)
    return _load_names(legacy_state_path())


def save_disabled(names) -> None:
    """原子写停用集合（排序去重，幂等）。"""
    _save_names(state_path(), names)


def is_disabled(name: str) -> bool:
    return str(name) in load_disabled()


def load_pinned() -> set:
    """读取固定技能名集合（新路径优先，旧路径兼容；缺失/破损 → 空集）。"""
    path = pinned_path()
    if path.exists():
        return _load_names(path)
    return _load_names(legacy_pinned_path())


def save_pinned(names) -> None:
    """原子写固定集合（排序去重，幂等）。"""
    _save_names(pinned_path(), names)


def is_pinned(name: str) -> bool:
    return str(name) in load_pinned()
