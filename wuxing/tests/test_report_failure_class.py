"""S1-C：报告与票据的失败分类呈现。"""
from wuxing.engine import _ticket_error_summary
from wuxing.protocols import UnitResult
from wuxing.reporting import build_report


def test_report_unit_line_has_class_suffix():
    units = [UnitResult(unit_id="F-1", domain_id="execute", status="failed",
                        failure_class="provider")]
    report = build_report(units, [])
    assert "F-1" in report and "基础设施失败" in report


def test_report_failure_composition_line():
    units = [
        UnitResult(unit_id="F-1", domain_id="execute", status="failed",
                   failure_class="provider"),
        UnitResult(unit_id="F-2", domain_id="execute", status="failed",
                   failure_class="budget"),
    ]
    report = build_report(units, [])
    assert "失败构成" in report
    assert "基础设施 1" in report and "可重跑" in report


def test_ticket_error_summary_marks_class():
    units = [UnitResult(unit_id="F-1", domain_id="execute", status="failed",
                        failure_class="provider")]
    s = _ticket_error_summary(units)
    assert "F-1:failed" in s and "基础设施" in s
