"""TDD：会话树（任务历史树——provenance 父子链 + task_state 任务根 + session 叶子）。"""
import pathlib
import tempfile

from wuxing.session_tree import build_task_tree, find_by_hash


def _mk_workdir():
    wd = pathlib.Path(tempfile.mkdtemp())
    (wd / ".wuxing").mkdir()
    (wd / ".wuxing" / "sessions").mkdir()
    return wd


def _write_state(wd, task_text="写一个请假应用"):
    from wuxing.protocols import Artifact, UnitResult
    from wuxing.state import TaskState, save_state
    state = TaskState(
        task_text=task_text,
        fragments=[{"fragment_id": "F-plan0", "domain": "plan", "deps": [],
                    "text": "制定方案"}, {"fragment_id": "F-exec1",
                    "domain": "execute", "deps": ["F-plan0"], "text": "实现"}],
        units=[
            UnitResult(unit_id="F-plan0", domain_id="plan", status="ok",
                       artifacts=[Artifact(path="F-plan0-plan.md", kind="plan",
                                           producer_unit="F-plan0")]),
            UnitResult(unit_id="F-exec1", domain_id="execute", status="failed",
                       error="guard: budget exhausted"),
        ],
        status="partial")
    save_state(state, wd / "task_state.json")


def _write_provenance(wd):
    from wuxing.provenance import ProvenanceLedger
    led = ProvenanceLedger(wd / ".wuxing" / "provenance.jsonl")
    led.record(unit_id="F-plan0", task_text="制定方案", goal="plan:制定方案",
               domain="plan", model="deepseek:deepseek-chat", status="ok",
               artifacts=["F-plan0-plan.md"])
    led.record(unit_id="F-exec1", task_text="实现", goal="实现应用",
               domain="execute", model="deepseek:deepseek-chat", status="failed")
    led.record(unit_id="delegate-写测试", parent_id="F-exec1", task_text="写测试",
               goal="写单元测试", domain="execute", model="deepseek:deepseek-chat",
               status="ok", artifacts=["test_app.py"])


def test_build_tree_task_unit_delegate_hierarchy():
    """任务根 → 单元 → delegate 子任务（parent 链）层级正确。"""
    wd = _mk_workdir()
    _write_state(wd)
    _write_provenance(wd)
    tree = build_task_tree(wd)
    assert tree is not None
    assert tree.type == "task"
    assert tree.label == "写一个请假应用"
    assert len(tree.children) == 2, f"两个单元：{[c.label for c in tree.children]}"
    exec_node = next(c for c in tree.children if c.id == "F-exec1")
    assert len(exec_node.children) == 1, "delegate 子任务挂接在父单元下"
    assert exec_node.children[0].type == "delegate"
    assert exec_node.children[0].label == "delegate-写测试"


def test_tree_status_and_artifacts_aggregated():
    """节点携带状态与产物（会话树信息完整）。"""
    wd = _mk_workdir()
    _write_state(wd)
    _write_provenance(wd)
    tree = build_task_tree(wd)
    assert tree.status == "partial"
    plan = next(c for c in tree.children if c.id == "F-plan0")
    assert plan.status == "ok"
    assert plan.artifacts == ["F-plan0-plan.md"]


def test_empty_workdir_returns_none():
    """无可恢复任务 → None（容错）。"""
    wd = _mk_workdir()
    assert build_task_tree(wd) is None


def test_find_by_hash():
    """按任务 hash 查询（内容寻址）。"""
    wd = _mk_workdir()
    _write_state(wd)
    tree = build_task_tree(wd)
    from wuxing.provenance import task_hash
    h = task_hash("写一个请假应用")
    found = find_by_hash(tree, h)
    assert found is not None and found.label == "写一个请假应用"
    assert find_by_hash(tree, "deadbeef") is None


def test_tree_renders_text_lines():
    """文本渲染（CLI 输出形态）。"""
    wd = _mk_workdir()
    _write_state(wd)
    _write_provenance(wd)
    tree = build_task_tree(wd)
    lines = tree.to_lines()
    assert any("写一个请假应用" in l for l in lines)
    assert any("delegate-写测试" in l for l in lines)
