"""任务状态持久化（P6：task_state.json——断点恢复的数据模型）。

TaskState = 任务级快照：fragments 定义 + units 结果 + artifacts 清单 + status。
save/load 纯 JSON（dataclass 序列化）。
"""
import json
import pathlib
from dataclasses import asdict, dataclass, field

from wuxing.atomic_write import atomic_write_text
from wuxing.protocols import Artifact, UnitResult


def _fix_artifact(d: dict) -> Artifact:
    """asdict 后 tuple 字段会变 list——恢复为 tuple。"""
    d = dict(d)
    if isinstance(d.get("depends_on"), list):
        d["depends_on"] = tuple(d["depends_on"])
    return Artifact(**d)

def _fix_unit(d: dict) -> UnitResult:
    d = dict(d)
    if isinstance(d.get("artifacts"), list):
        d["artifacts"] = [_fix_artifact(a) if isinstance(a, dict) else a
                          for a in d["artifacts"]]
    return UnitResult(**d)

@dataclass
class TaskState:
    task_text: str
    fragments: list = field(default_factory=list)
    units: list = field(default_factory=list)      # [UnitResult]
    artifacts: list = field(default_factory=list)  # [Artifact]
    status: str = "running"

def save_state(state: TaskState, path: pathlib.Path):
    data = {
        "task_text": state.task_text,
        "fragments": state.fragments,
        "units": [asdict(u) for u in state.units],
        "artifacts": [asdict(a) for a in state.artifacts],
        "status": state.status,
    }
    # C2：原子写（tmp + replace——崩溃不产生半写损坏；Windows 瞬态占用重试）
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def runs_dir(workdir) -> pathlib.Path:
    """run 作用域状态目录（G8-M3）：`<workdir>/.wuxing/runs/<run_id>/`。"""
    return pathlib.Path(workdir) / ".wuxing" / "runs"


def run_state_path(workdir, run_id) -> pathlib.Path:
    """指定 run 的任务状态路径。"""
    return runs_dir(workdir) / str(run_id) / "task_state.json"


def latest_run_id(workdir) -> str | None:
    """最新 run（按 task_state.json mtime）；无 → None。"""
    best, best_m = None, -1.0
    try:
        for p in runs_dir(workdir).iterdir():
            f = p / "task_state.json"
            if f.is_file():
                m = f.stat().st_mtime
                if m > best_m:
                    best, best_m = p.name, m
    except OSError:
        # 状态目录不可读 → None（定位最新状态失败）
        return None
    return best


def latest_state_path(workdir) -> pathlib.Path:
    """断点恢复读取路径：最新 run 状态优先，根级旧路径回退（兼容）。"""
    rid = latest_run_id(workdir)
    if rid:
        return run_state_path(workdir, rid)
    return pathlib.Path(workdir) / "task_state.json"


def load_state(path: pathlib.Path) -> TaskState:
    if not pathlib.Path(path).exists():
        raise FileNotFoundError(f"task state not found: {path}")
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return TaskState(
        task_text=data["task_text"],
        fragments=data.get("fragments", []),
        units=[_fix_unit(u) for u in data.get("units", [])],
        artifacts=[_fix_artifact(a) for a in data.get("artifacts", [])],
        status=data.get("status", "running"))
