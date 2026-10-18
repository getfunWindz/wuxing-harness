"""壳侧持久状态（UI 重构 · 阶段 2.3）——回收站记录（归档 / 删除）。

安全语义（设计 §5.1）：
- 壳的记录操作**不删除磁盘上的用户产物**；
- 会话等引擎数据的实际删除仅在显式 `purge`（且二次确认）时执行。
"""
import json
import os
import pathlib
import time
import uuid

from wuxing.atomic_write import atomic_write_text


def _norm(path) -> str:
    try:
        return os.path.normcase(os.path.abspath(str(path)))
    except (TypeError, ValueError):
        # 非法路径输入 → 空串（归一化失败；调用方按不匹配处理）
        return ""


def norm_path(path) -> str:
    """路径规范化（跨平台比较用；供壳内模块复用）。"""
    return _norm(path)


def same_path(a, b) -> bool:
    return bool(a) and bool(b) and _norm(a) == _norm(b)


class RecycleStore:
    """回收站存储（默认持久化；path=None → 内存模式，供测试/无状态场景）。"""

    def __init__(self, path=None):
        self.path = pathlib.Path(path) if path else None
        self._entries: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._entries = [e for e in data if isinstance(e, dict)]
        except (OSError, ValueError):
            self._entries = []

    def _save(self) -> None:
        if not self.path:
            return
        atomic_write_text(
            self.path, json.dumps(self._entries, ensure_ascii=False, indent=1))

    def list(self) -> list[dict]:
        return [dict(e) for e in self._entries]

    def find(self, entry_id: str) -> dict | None:
        for e in self._entries:
            if e.get("id") == entry_id:
                return e
        return None

    def add(self, *, kind: str, state: str, name: str,
            path: str = "", ws_path: str = "", folder: str = "") -> dict:
        entry = {
            "id": uuid.uuid4().hex[:12],
            "kind": kind,                 # workspace | session
            "state": state,               # archived | trashed
            "name": name,
            "path": str(path),
            "ws_path": str(ws_path),
            "folder": str(folder),        # 工作区分组归属（恢复时回填）
            "ts": round(time.time(), 3),
        }
        self._entries.append(entry)
        self._save()
        return dict(entry)

    def remove(self, entry_id: str) -> dict | None:
        e = self.find(entry_id)
        if e is None:
            return None
        self._entries = [x for x in self._entries if x.get("id") != entry_id]
        self._save()
        return dict(e)

    def hidden_run_ids(self, ws_path: str) -> set[str]:
        """该工作区下被归档/删除（应从任务列表隐藏）的任务 run_id。"""
        out = set()
        for e in self._entries:
            if e.get("kind") == "task" and same_path(e.get("ws_path"), ws_path):
                out.add(str(e.get("path")))
        return out

    def hidden_session_paths(self, ws_path: str) -> set[str]:
        """该工作区下被归档/删除（应从活动列表隐藏）的会话文件路径。"""
        out = set()
        for e in self._entries:
            if e.get("kind") == "session" and same_path(e.get("ws_path"), ws_path):
                out.add(_norm(e.get("path")))
        return out
