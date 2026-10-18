"""执行会话日志（P4 T2：append-only jsonl——消息级回放材料，增量语义）。

与 provenance 并置（workdir/.wuxing/sessions/）；损坏行跳过（韧性惯例——
回放是观测不是生命线）。为 RL 轨迹留原料（知识库「观测」标准）。

记录结构（增量语义——回放拼接无重复，审查 2026-09-05 修正）：
  seed 行    ：round=0（初始 system+prompt——回放上下文头）
  增量行     ：每轮新增消息（LLM 输出 + 工具结果），不含历史
  终结行     ：state=done/failed + status（messages 为空——标记行）
"""
import json
import logging
import pathlib
import time

logger = logging.getLogger(__name__)


class SessionLog:
    def __init__(self, path: pathlib.Path):
        self.path = pathlib.Path(path)

    def seed(self, messages: list) -> None:
        """初始消息（round=0——回放上下文头；resume 场景不重复 seed）。"""
        self._write(round_no=0, state="seed", messages=messages, status="")

    def append(self, round_no: int, state: str, messages: list,
               status: str = "") -> None:
        """追加一轮【增量】记录（append-only——不覆写历史行）。"""
        self._write(round_no=round_no, state=state, messages=messages,
                    status=status)

    def _write(self, round_no: int, state: str, messages: list,
               status: str) -> None:
        # H6（E3-5）：call-time 注入帧（`_call_time`）不写档案——transcript=真实历史
        msgs = [m for m in messages
                if not (isinstance(m, dict) and m.get("_call_time"))]
        line = {
            "round": round_no,
            "state": state,
            "status": status,
            "ts": round(time.time(), 3),
            "messages": [{"role": m.get("role", ""),
                          "content": str(m.get("content", ""))}
                         for m in msgs],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.debug("会话存档写入失败（不阻断）：%s", exc)

    def load(self) -> list:
        """读取全部记录（损坏行跳过）。"""
        if not self.path.exists():
            return []
        rows = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except (ValueError, json.JSONDecodeError):
                        continue
        except OSError:
            return []
        return rows

    def last_messages(self) -> list:
        """回放材料：seed 行 + 各轮增量的顺序拼接（完整且无重复）。"""
        hist = []
        for row in self.load():
            hist.extend(row.get("messages", []))
        return hist
