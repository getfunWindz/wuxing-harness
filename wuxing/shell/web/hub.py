"""EventHub（壳 P1 · B1）——并发健壮的进程内事件枢纽（传输无关）。

设计 §4.2：
  - 信封 {v, epoch, seq, ts, workspace_id, run_id, type, data}；
  - seq：单锁分配，**全局全序**（客户端唯一顺序基准）；
  - epoch：实例标识（服务重启即变——客户端据此清缓存并重拉快照）；
  - 环形缓冲：`since` 重放；覆盖不足 → gap 标记（服务端转 resync_required）；
  - 背压：订阅者**有界队列**——溢出即断开该订阅者（生产者永不被阻塞）；
  - 载荷纪律：只带 ID/状态/路径（正文一律走 REST）。
"""
import collections
import json
import os
import pathlib
import queue
import threading
import time
import uuid

from .version import API_VERSION


class _Closed:
    """订阅关闭哨兵（已断开/已注销——消费方据此收尾）。"""
    __slots__ = ()


CLOSED = _Closed()


class Subscription:
    """订阅者（有界队列；溢出即断开——不影响生产者）。"""

    __slots__ = ("_closed", "_q", "dropped", "gap")

    def __init__(self, maxsize: int = 1000):
        self._q = queue.Queue(maxsize=max(1, int(maxsize)))
        self._closed = threading.Event()
        self.dropped = False   # 因溢出被断开
        self.gap = False       # since 重放缺口（需客户端重拉快照）

    def offer(self, event: dict) -> bool:
        """非阻塞投递；溢出 → 标记断开（生产者不受影响）。"""
        if self._closed.is_set():
            return False
        try:
            self._q.put_nowait(event)
            return True
        except queue.Full:
            self.dropped = True
            self._closed.set()
            return False

    def close(self) -> None:
        self._closed.set()

    def get(self, timeout: float = 15.0):
        """取事件；超时 → None（供心跳）；断开且已排空 → CLOSED。"""
        end = time.monotonic() + max(0.0, timeout)
        while True:
            if self._closed.is_set() and self._q.empty():
                return CLOSED
            remaining = end - time.monotonic()
            if remaining <= 0:
                if self._closed.is_set() and self._q.empty():
                    return CLOSED
                return None
            try:
                return self._q.get(timeout=min(remaining, 0.2))
            except queue.Empty:
                continue


class EventHub:
    """进程内事件枢纽（线程安全；传输层由 server 决定 SSE/WS）。"""

    def __init__(self, ring_size: int = 4096, subscriber_queue: int = 1000,
                 journal_path=None, journal_max_bytes: int = 2_000_000):
        self._lock = threading.Lock()
        self._subs = set()
        self._ring = collections.deque(maxlen=max(1, int(ring_size)))
        self._seq = 0
        self.epoch = uuid.uuid4().hex[:12]
        self._sub_queue = max(1, int(subscriber_queue))
        # 事件日志（B6 可选加固）：审计/调试/复盘；不承担重启重放正确性
        self._journal_path = (pathlib.Path(journal_path)
                              if journal_path else None)
        self._journal_max = max(1024, int(journal_max_bytes))
        self._journal_lock = threading.Lock()
        self._journal_failed = False  # 写失败后停写（防反复报错）

    def emit(self, type: str, workspace_id: str = "", run_id: str = "",
             data: dict | None = None) -> dict:
        """产生事件（分配 seq；扇出到订阅者；永不阻塞）。"""
        with self._lock:
            self._seq += 1
            ev = {"v": API_VERSION, "epoch": self.epoch, "seq": self._seq,
                  "ts": round(time.time(), 3),
                  "workspace_id": workspace_id, "run_id": run_id,
                  "type": type, "data": data or {}}
            self._ring.append(ev)
            subs = list(self._subs)
        for s in subs:
            s.offer(ev)
        self._journal(ev)
        return ev

    def _journal(self, ev: dict) -> None:
        """事件日志（best-effort——失败静默不阻断；超上限单备份轮转）。"""
        if self._journal_path is None or self._journal_failed:
            return
        with self._journal_lock:
            try:
                self._journal_path.parent.mkdir(parents=True, exist_ok=True)
                if (self._journal_path.exists()
                        and self._journal_path.stat().st_size
                        >= self._journal_max):
                    os.replace(self._journal_path,
                               self._journal_path.with_suffix(".jsonl.1"))
                with open(self._journal_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            except OSError:
                self._journal_failed = True

    def subscribe(self, since: int | None = None):
        """创建订阅者 → (sub, 重放事件, gap)。

        gap=True：since 之前缓冲不可覆盖——服务端应发 resync_required，
        客户端重拉 snapshot 后以新 since 再订阅。
        """
        sub = Subscription(self._sub_queue)
        replay, gap = [], False
        with self._lock:
            if since is not None:
                oldest = self._ring[0]["seq"] if self._ring else self._seq + 1
                if int(since) + 1 < oldest:
                    gap = True
                elif int(since) < self._seq:
                    replay = [e for e in self._ring if e["seq"] > int(since)]
            # 先入列重放、后挂载扇出（同一把锁内）——并发 emit 的实时事件
            # 只会追加在重放之后，队列内 seq 保序
            for ev in replay:
                if not sub.offer(ev):
                    break
            self._subs.add(sub)
        sub.gap = gap
        return sub, replay, gap

    def unsubscribe(self, sub: Subscription) -> None:
        sub.close()
        with self._lock:
            self._subs.discard(sub)

    def info(self) -> dict:
        with self._lock:
            return {"epoch": self.epoch, "last_seq": self._seq,
                    "subscribers": len(self._subs),
                    "ring": len(self._ring)}
