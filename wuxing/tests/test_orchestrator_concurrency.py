"""TDD：宽 DAG 并发压测（mock）——并行度天花板验证（确定性口径）。

口径：Barrier(4) 强制 4 个单元必须同时在跑才放行——若调度未并行，
会有单元在 3s 内等不到同伴而 BrokenBarrierError（确定性失败，无时序抖动）。
墙钟曲线由 pilot bench 采集（不作为单测断言）。
"""
import pathlib
import tempfile
import threading
import time

from wuxing.config import EngineConfig
from wuxing.orchestrator import Orchestrator
from wuxing.protocols import UnitResult
from wuxing.registry import DomainRegistry
from wuxing.workspace import Workspace


class _CountingRunner:
    emit_event = None

    def __init__(self, state, barrier):
        self.state = state
        self.barrier = barrier

    def run_unit(self, unit_id, domain_id, params, resume_session=None,
                 bypass_confirm=False, continue_from=None, cancel=None,
                 llm_candidate=0):
        with self.state["lock"]:
            self.state["active"] += 1
            self.state["max_active"] = max(self.state["max_active"],
                                           self.state["active"])
        try:
            if self.barrier is not None:
                self.barrier.wait(timeout=3)  # 4 单元必须真正同时在跑
            else:
                time.sleep(0.05)
        finally:
            with self.state["lock"]:
                self.state["active"] -= 1
        return UnitResult(unit_id=unit_id, domain_id=domain_id, status="ok")


def _bench(parallel: int, n_units: int = 4) -> dict:
    cfg = EngineConfig(max_parallel_units=parallel)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    state = {"lock": threading.Lock(), "active": 0, "max_active": 0}
    barrier = threading.Barrier(n_units) if parallel >= n_units else None
    o = Orchestrator(cfg, DomainRegistry(cfg), ws, None, [])
    o._make_runner = lambda: _CountingRunner(state, barrier)
    frags = [{"fragment_id": f"F-{i}", "domain": "execute", "deps": [],
              "text": f"t{i}"} for i in range(n_units)]
    o.run(frags, "bench")
    return state["max_active"]


def test_wide_dag_concurrency_mock():
    """4 独立单元：parallel=1 严格串行（=1）；parallel=4 必须满并发（=4，屏障证据）。"""
    assert _bench(1) == 1, "串行必须严格 1"
    assert _bench(4) == 4, "并发必须真正同时执行 4 个单元（屏障放行）"
