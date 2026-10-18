"""trace 采集器（L1-1 · 评测原料——知识库「trace=评测原料」标准落地）。

Append-only JSONL（workdir/.wuxing/trace.jsonl）——每次执行的事件时间线：
  unit_started : 单元开始 {ts, unit_id, domain}
  llm_call     : LLM 轮次 {ts, unit_id, round, input, output, cache_read, cache_write, latency_ms}
  tool_call    : 工具调用 {ts, unit_id, round, name, arg_hash, status, latency_ms}
  contract_check : 契约判定 {ts, unit_id, round, passed}
  unit_done    : 单元结束 {ts, unit_id, status, verdict_fail}

设计纪律：
  - 观测不是生命线：写失败静默（try/except——与 session/provenance 韧性惯例一致）
  - 线程安全：P16 并行碎片同写一文件——append 互斥（锁 + 单次 write）
  - 可回放：行序即事件序（单元按 unit_id 过滤后天然单调）
"""
import json
import logging
import pathlib
import threading
import time

from wuxing.filelock import lock_for

logger = logging.getLogger(__name__)


class TraceLogger:
    def __init__(self, path: pathlib.Path):
        self.path = pathlib.Path(path)
        self._lock = threading.Lock()

    def log(self, event: str, unit_id: str, domain: str = "", **fields) -> None:
        """追加一条事件（原子单行写；失败静默——观测不阻断执行）。"""
        line = {"ts": round(time.time(), 3), "event": event,
                "unit_id": unit_id, "domain": domain, **fields}
        try:
            with lock_for(self.path), self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.debug("trace 写入失败（观测不阻断）：%s", exc)

    def load(self) -> list:
        """读取全部事件（损坏行跳过——韧性惯例）。"""
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
                        continue
        except OSError:
            return []
        return rows

    def for_unit(self, unit_id: str) -> list:
        """按单元过滤（评测回放视角）。"""
        return [x for x in self.load() if x.get("unit_id") == unit_id]

    def clear(self) -> None:
        """清空（评测场景隔离——每轮评测独立 trace）。"""
        try:
            with lock_for(self.path):
                if self.path.exists():
                    self.path.unlink()
        except OSError as exc:
            logger.debug("trace 清理失败（不阻断）：%s", exc)
