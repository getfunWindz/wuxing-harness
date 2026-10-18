"""TDD：P5 拆分新增——成本估算（usage 真值 → 元；表驱动）。"""
from wuxing.reporting import build_report, estimate_cost


def test_estimate_cost_default_prices():
    """默认参考单价（DeepSeek：未命中 1/命中缓存 0.1/输出 2 元每百万）。"""
    usage = {"input": 100_000, "output": 50_000, "cache_read": 200_000,
             "cache_write": 0}
    cost = estimate_cost(usage)
    assert abs(cost - (0.1 * 1.0 + 0.05 * 2.0 + 0.2 * 0.1)) < 1e-6, cost


def test_estimate_cost_empty_is_zero():
    """无 usage → 0 元（报告不显示成本行）。"""
    assert estimate_cost({}) == 0.0


def test_build_report_shows_cost_when_positive():
    """有成本 → 报告含「估算成本」行；零成本 → 不显示。"""
    m1 = {"llm_calls": 1, "usage": {"input": 100_000, "output": 0,
                                    "cache_read": 0, "cache_write": 0}}
    r1 = build_report([], [], m1)
    assert "估算成本" in r1
    m2 = {"llm_calls": 0, "usage": {"input": 0, "output": 0,
                                    "cache_read": 0, "cache_write": 0}}
    r2 = build_report([], [], m2)
    assert "估算成本" not in r2


def test_report_artifact_list_excludes_internal():
    """Task A4（Wave-1）：用户面报告产物列表滤除内部产物。

    F-* 契约报告是给模型看的过程记录（用户裁决 2026-10-01）——不得进
    用户可见报告；计数与明细同源（过滤后）。
    真机补充（2026-10-03）：报告生成于归档前——契约报告彼时为裸路径
    （F-0001-result.md）且 kind 为契约类型；过滤须与归档同源（kind）。
    """
    from wuxing.protocols import Artifact, UnitResult
    u = UnitResult(unit_id="F-1", domain_id="execute", status="ok")
    arts = [Artifact(path="index.html", kind="site"),
            Artifact(path=".wuxing/reports/F-1-result.md", kind="result"),
            Artifact(path="F-0001-result.md", kind="result"),   # 归档前形态
            Artifact(path="notes.md", kind="")]
    text = build_report([u], arts)
    assert "index.html" in text and "notes.md" in text
    assert "F-1-result.md" not in text      # 中间产物不进用户报告
    assert "F-0001-result.md" not in text   # 归档前裸路径同样不得出现
    assert "产物 2 个" in text               # 计数与明细同源（过滤后）


def test_report_internal_kinds_in_sync_with_engine():
    """真机补充（2026-10-03）：报告过滤与归档必须同源（kind 集合不得漂移）。"""
    from wuxing.engine import Engine
    from wuxing.reporting import _INTERNAL_KINDS
    assert set(_INTERNAL_KINDS) == set(Engine._REPORT_KINDS)
