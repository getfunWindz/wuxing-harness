"""SSE 事件流路由（Q1：自 api.py register_api 逐字迁移）。"""
import json

from wuxing.shell.web.hub import CLOSED
from wuxing.shell.web.server import StreamResponse, error_response

from .base import _guard

_HEARTBEAT_S = 15.0


def _sse_frame(event_type: str | None, payload: dict, event_id=None) -> str:
    """SSE 帧。event_type=None → 未命名 message 帧（常规事件；新增类型无需前端白名单）。

    命名帧仅用于控制通道（hello / resync_required）。
    """
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    if event_type:
        lines.append(f"event: {event_type}")
    lines.append("data: " + json.dumps(payload, ensure_ascii=False))
    return "\n".join(lines) + "\n\n"


def register(server, ctx) -> None:
    hub = ctx.hub

    @_guard
    def h_events(req):
        since_raw = req.query.get("since")
        since = None
        if since_raw not in (None, ""):
            try:
                since = int(since_raw)
            except ValueError:
                return error_response(422, "invalid", "since 必须为整数")
        sub, _replay, gap = hub.subscribe(since)
        info = hub.info()

        def stream():
            try:
                yield _sse_frame("hello", {"epoch": info["epoch"],
                                           "last_seq": info["last_seq"],
                                           "gap": bool(gap)})
                if gap:
                    # 缓冲覆盖不足：客户端重拉 snapshot 后以新 since 再订阅
                    yield _sse_frame("resync_required",
                                     {"epoch": info["epoch"],
                                      "last_seq": info["last_seq"]})
                    return
                while True:
                    ev = sub.get(timeout=_HEARTBEAT_S)
                    if ev is None:
                        yield ": ping\n\n"  # 心跳（连接存活/清僵尸）
                        continue
                    if ev is CLOSED:
                        break
                    # 常规事件 = 未命名 message 帧：引擎新增事件类型自动到达客户端
                    # （未知类型由前端安全忽略——设计 §9 事件扩展缝）
                    yield _sse_frame(None, ev, event_id=ev["seq"])
            finally:
                hub.unsubscribe(sub)

        return StreamResponse(stream())

    server.add_route("GET", r"^/api/v1/events$", h_events)
