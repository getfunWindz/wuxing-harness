import os
import pathlib
import random
import tempfile
import time

import pytest

from wuxing.engine import Engine
from wuxing.router import route_fragment

# CI 负载可能高于本机；默认 30s，CI 可用环境变量放宽（不改变本机口径）
_DAG_LIMIT_S = float(os.environ.get("WUXING_STRESS_DAG_LIMIT_S", "30"))


def _mk_eng():
    return Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)

@pytest.mark.slow
def test_500_chain_dag():
    eng = _mk_eng()
    frags = [{"fragment_id": f"F-{i}", "domain": route_fragment(f"实现单元{i}"),
              "deps": [f"F-{i-1}"] if i > 0 else []} for i in range(500)]
    t0 = time.time()
    results = eng.orchestrator.run(frags, "压力")
    assert len(results) == 500
    assert all(r.status == "ok" for r in results)
    assert time.time() - t0 < _DAG_LIMIT_S  # 韧性：可接受时间（CI 可放宽）

@pytest.mark.slow
def test_500_shuffled_dag():
    eng = _mk_eng()
    frags = [{"fragment_id": f"F-{i}", "domain": route_fragment(f"实现单元{i}"),
              "deps": [f"F-{i-1}"] if i > 0 else []} for i in range(500)]
    random.seed(42)
    random.shuffle(frags)
    t0 = time.time()
    results = eng.orchestrator.run(frags, "乱序压力")
    assert len(results) == 500
    assert all(r.status == "ok" for r in results)
    assert time.time() - t0 < _DAG_LIMIT_S

@pytest.mark.slow
def test_cycle_dag_detected():
    eng = _mk_eng()
    bad = [{"fragment_id": "F-1", "domain": "execute", "deps": ["F-2"]},
           {"fragment_id": "F-2", "domain": "execute", "deps": ["F-1"]}]
    results = eng.orchestrator.run(bad, "环")
    assert all(r.status == "failed" for r in results)
    assert all("cycle" in (r.error or "") for r in results)
