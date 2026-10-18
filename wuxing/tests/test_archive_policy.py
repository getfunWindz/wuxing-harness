"""归档策略与缓存一致性（真跑 T-5 误判根因 · 2026-10-03）。

真机链路：verify 命中确认门 → 任务 pending 返回时**即归档**（契约报告移入
.wuxing/reports/）→ 壳确认回路放行 → 确认路径 _dep_context 经 **file_cache
陈旧快照**注入已移动路径 → 机制 `_verify_deps_missing` 磁盘读全缺失 →
误判「产物缺失 → 不通过」（T-5 verdict_fail / theroad-tickets FAIL）。

修复：①pending（等待确认）不归档——终态才归档；②归档移动后失效 file_cache。
"""
import pathlib

from wuxing.engine import Engine
from wuxing.protocols import Artifact, TaskResult, UnitResult


def _res(status: str, path: str = "F-1-result.md") -> TaskResult:
    art = Artifact(path=path, kind="result", producer_unit="F-1")
    u = UnitResult(unit_id="F-1", domain_id="execute", status="ok",
                   artifacts=[art], deliverables=[path])
    return TaskResult(task_text="t", fragments=[], units=[u],
                      artifacts=[art], status=status)


def test_pending_result_not_archived_until_terminal(tmp_path):
    eng = Engine(workdir=pathlib.Path(tmp_path))
    root = tmp_path / "F-1-result.md"
    root.write_text("body", encoding="utf-8")
    res = _res("pending")
    eng._maybe_archive_reports(res)
    assert root.exists(), "pending（等待确认）产物必须留在原位"
    assert not (tmp_path / ".wuxing" / "reports" / "F-1-result.md").exists()
    res.status = "done"
    eng._maybe_archive_reports(res)
    assert not root.exists()
    assert (tmp_path / ".wuxing" / "reports" / "F-1-result.md").exists()


def test_archive_invalidates_file_cache(tmp_path):
    eng = Engine(workdir=pathlib.Path(tmp_path))
    (tmp_path / "F-1-result.md").write_text("body", encoding="utf-8")
    eng.file_cache.put("F-1-result.md", "body")   # 模拟曾读取（陈旧快照）
    eng._archive_internal_reports(_res("done"))
    assert eng.file_cache.get("F-1-result.md") is None, \
        "归档移动后 file_cache 旧路径必须失效（防确认/续跑注入已移动路径）"
