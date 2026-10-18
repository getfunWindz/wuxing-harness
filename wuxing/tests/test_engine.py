import pathlib
import tempfile
import typing

from wuxing.engine import Engine

_E = None
def _mk_engine():
    global _E
    if _E is None:
        _E = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    return _E

def test_engine_run_task_end_to_end():
    eng = _mk_engine()
    result = eng.run_task("写一篇请假邮件")
    assert result.status == "done"
    assert len(result.fragments) >= 1
    assert len(result.artifacts) >= 1
    assert result.report != ""


def test_result_artifacts_includes_real_deliverables():
    """2026-10-01 真机 P1：任务产物清单 = 契约产物 + 真实交付物（去重保序）。

    现场：模型用 write_file 写出 index.html/src/*（真实交付物），但只把
    write_artifact 契约文件计入 TaskResult.artifacts → UI/报告只列报告文件，
    用户判定「只生产了报告没有生成网站本身」。"""
    from wuxing.engine import result_artifacts
    from wuxing.protocols import Artifact

    class _U:
        unit_id = "F-1"
        artifacts: typing.ClassVar = [Artifact(path="F-1-result.md", kind="result")]
        deliverables: typing.ClassVar = ["index.html", "src/a.css", "F-1-result.md"]

    out = result_artifacts([_U()])
    paths = [a.path for a in out]
    assert paths == ["F-1-result.md", "index.html", "src/a.css"]
    by_path = {a.path: a for a in out}
    assert by_path["index.html"].producer_unit == "F-1"


def test_result_artifacts_empty_units():
    from wuxing.engine import result_artifacts
    assert result_artifacts([]) == []


def test_internal_reports_archived_after_run(tmp_path):
    """2026-10-01 用户裁决：契约报告（给模型看的）收纳到 .wuxing/reports/，
    工作区根目录只留真实交付物（给用户看的）——归档同步单元与清单引用。"""
    from wuxing.engine import Engine
    from wuxing.llm.factory import create_provider
    from wuxing.protocols import Artifact, TaskResult, UnitResult
    eng = Engine(workdir=tmp_path, llm=create_provider("mock"), auto_confirm=True)
    eng.ws.write_artifact(Artifact(path="F-0001-result.md", kind="result"), "报告")
    (tmp_path / "site.html").write_text("<html>", encoding="utf-8")
    u = UnitResult(unit_id="F-0001", domain_id="execute", status="ok",
                   artifacts=[Artifact(path="F-0001-result.md", kind="result")],
                   deliverables=["F-0001-result.md", "site.html"])
    res = TaskResult(task_text="t", fragments=[], units=[u],
                     artifacts=list(u.artifacts), status="done")
    eng._archive_internal_reports(res)
    assert not (tmp_path / "F-0001-result.md").exists()
    assert (tmp_path / ".wuxing" / "reports" / "F-0001-result.md").is_file()
    assert u.artifacts[0].path == ".wuxing/reports/F-0001-result.md"
    assert ".wuxing/reports/F-0001-result.md" in u.deliverables
    assert (tmp_path / "site.html").is_file(), "真实交付物不得归档"
    paths = [a.path for a in eng.ws.manifest()]
    assert ".wuxing/reports/F-0001-result.md" in paths

def test_engine_run_realistic_task():
    eng = _mk_engine()
    result = eng.run_task("开发一个带用户登录的网站")
    assert result.status in ("done", "partial")
    assert len(result.fragments) >= 1

def test_engine_uses_golden_ratio_segmentation():
    eng = _mk_engine()
    result = eng.run_task("开发一个带用户登录的网站")
    # 完整形态：碎片来自 golden_ratio 分割而非硬编码三链
    assert result.fragments != [
        {"fragment_id": "F-1", "domain": "plan", "deps": []},
        {"fragment_id": "F-2", "domain": "execute", "deps": ["F-1"]},
        {"fragment_id": "F-3", "domain": "verify", "deps": ["F-2"]},
    ]
    assert len(result.fragments) >= 1


def test_engine_assembles_delegate_and_provenance():
    """3c：Engine 装配 delegate 工具 + 溯源链（真实链路装配检查）。"""
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    assert eng.tools.get("delegate") is not None
    assert eng.provenance is not None
    # 白名单：plan/execute 域含 delegate（用户决策 A）
    plan = eng.registry.get("plan")
    assert "delegate" in plan.tool_whitelist
    assert "delegate" in eng.registry.get("execute").tool_whitelist


def test_engine_run_task_writes_provenance():
    """3c：run_task 后溯源链有记录（单元级）。"""
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    eng.run_task("写一篇请假邮件")
    rows = eng.provenance.load()
    assert len(rows) >= 1
    assert rows[0]["domain"] in ("plan", "execute", "verify")
    assert "task_hash" in rows[0]


def test_engine_sets_session_cache_key_on_provider():
    """Pi 同款集成：Engine 构造后 provider 必须携带会话亲和键（工作区标识）。"""
    import pathlib
    import tempfile

    from wuxing.engine import Engine
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    key = getattr(eng.llm, "_cache_key", "")
    assert key, "Engine 必须设置 _cache_key（工作区标识）"
    assert len(key) <= 64, "键必须 ≤64 字符（OpenAI 限制）"


def test_run_task_archives_reports_end_to_end(tmp_path):
    """接线验证：run_task 完成后契约报告自动归档，根目录只留真实交付物。"""
    from wuxing.llm.tool_results import ToolCallResult

    class _Llm:
        def name(self): return "arch"
        def spec(self): return "arch"
        def chat(self, messages, tools=None):
            text = " ".join(m.get("content", "") for m in messages)
            if "域：plan" in text:
                return ToolCallResult(text="方案", tool_calls=[{
                    "name": "write_artifact",
                    "arguments": {"path": "plan.md", "kind": "plan", "content": "方案"}}])
            if "域：execute" in text:
                return ToolCallResult(text="完成", tool_calls=[
                    {"name": "write_artifact",
                     "arguments": {"path": "out-result.md", "kind": "result", "content": "完成"}},
                    {"name": "write_file",
                     "arguments": {"path": "app.py", "content": "print(1)"}},
                ])
            return ToolCallResult(text="结论：通过", tool_calls=[{
                "name": "write_artifact",
                "arguments": {"path": "v-verdict.md", "kind": "verdict",
                              "content": "结论：通过"}}])

    eng = Engine(workdir=tmp_path, llm=_Llm(), auto_confirm=True)
    result = eng.run_task("写一个输出一的小程序")
    # 核心不变量：契约报告（F-*-plan/result/verdict.md）不得留在根目录
    root_f_reports = [p.name for p in tmp_path.glob("F-*.md")]
    assert root_f_reports == [], f"契约报告泄露到根目录：{root_f_reports}"
    reports = tmp_path / ".wuxing" / "reports"
    assert reports.is_dir() and any(reports.glob("*-plan.md"))
    assert all(not a.path.startswith("F-") or
               a.path.replace("\\", "/").startswith(".wuxing/")
               for a in result.artifacts), "任务产物引用必须指向归档后路径"
