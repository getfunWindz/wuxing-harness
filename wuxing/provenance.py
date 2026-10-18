"""任务溯源链（3c 决策 C——git 参考：内容 hash + 父子链 + append-only 日志）。

设计语义（可溯源路径 = 产物文件路径 + provenance 记录）：
  task_hash  任务文本 sha256 前 8 位（内容寻址——git blob 思想）
  parent_id  执行单元父子链（子代理/委托——git commit parent 思想）
  append-only JSONL（git reflog 思想——不可篡改的追加日志）
  损坏容错：单行损坏跳过（韧性护栏惯例）

路径：workdir/.wuxing/provenance.jsonl（.wuxing 为引擎内部数据目录）
"""
import hashlib
import json
import logging
import pathlib
import threading
import time
import uuid

from wuxing.filelock import lock_for

logger = logging.getLogger(__name__)


def task_hash(text: str) -> str:
    """任务文本内容寻址（git blob 思想：同内容同指纹）。"""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]


class ProvenanceLedger:
    """append-only 溯源日志（单元粒度）。"""

    def __init__(self, path: pathlib.Path):
        self.path = pathlib.Path(path)
        self._lock = threading.Lock()  # P16：并发 append 互斥

    def record(self, unit_id: str, parent_id: str = "", task_text: str = "",
               goal: str = "", domain: str = "", model: str = "",
               status: str = "", artifacts: list | None = None) -> dict:
        """追加一条溯源记录（返回写入的行——包含 provenance_id）。"""
        line = {
            "provenance_id": uuid.uuid4().hex[:12],   # 记录ID（溯源锚点）
            "unit_id": unit_id,
            "parent_id": parent_id,
            "task_hash": task_hash(task_text),
            "goal": goal,
            "domain": domain,
            "model": model,
            "status": status,
            "artifacts": list(artifacts or []),
            "ts": round(time.time(), 3),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # C1：并发 append 互斥（原锁创建未使用——死锁修复）；
            # G8-M2：跨 Engine 实例共享路径锁
            with lock_for(self.path), self._lock, open(self.path, "a",
                                                       encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.debug("溯源写入失败（不阻断）：%s", exc)
        return line

    def load(self) -> list:
        """读取全部记录（损坏单行跳过）。"""
        if not self.path.exists():
            return []
        rows = []
        try:
            with lock_for(self.path), open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue  # 单行损坏跳过
        except OSError:
            return []
        return rows

    def find(self, unit_id: str) -> dict | None:
        """按 unit_id 查找（最近一次）。"""
        for row in reversed(self.load()):
            if row.get("unit_id") == unit_id:
                return row
        return None

    def descendants(self, provenance_id: str) -> list:
        """子链查询（parent 链接——git commit 思想）。"""
        all_rows = self.load()
        by_parent = {}
        for row in all_rows:
            by_parent.setdefault(row.get("parent_id"), []).append(row)
        out = []
        stack = list(by_parent.get(provenance_id, []))
        while stack:
            row = stack.pop()
            out.append(row)
            stack.extend(by_parent.get(row.get("provenance_id"), []))
        return out
