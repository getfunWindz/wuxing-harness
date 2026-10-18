"""TDD：精确测试框架（B；原称准测试）——任务数据装载与校验（防泄漏红线之数据侧）。"""
import json
import pathlib

import pytest

from wuxing.accuracy import load_tasks, validate_task


def _base() -> dict:
    return {
        "id": "acc-x",
        "title": "示例任务",
        "public_prompt": "一句话需求",
        "hidden_rubric": {
            "version": "v1",
            "items": [{"id": "R1", "desc": "可运行程序", "weight": 3,
                       "checks": ["文件存在", "可执行"]}],
            "pass_line": 0.6,
        },
        "evidence_checklist": ["主文件存在"],
    }


def test_validate_task_ok():
    assert validate_task(_base())["id"] == "acc-x"


@pytest.mark.parametrize("field", ["id", "title", "public_prompt",
                                   "hidden_rubric", "evidence_checklist"])
def test_validate_task_requires_fields(field):
    t = _base()
    t.pop(field)
    with pytest.raises(ValueError, match=field):
        validate_task(t)


def test_validate_task_rejects_bad_rubric():
    t = _base()
    t["hidden_rubric"]["items"] = []
    with pytest.raises(ValueError, match="items"):
        validate_task(t)

    t = _base()
    t["hidden_rubric"]["items"][0]["weight"] = 0
    with pytest.raises(ValueError, match="weight"):
        validate_task(t)

    t = _base()
    t["hidden_rubric"]["items"].append(dict(t["hidden_rubric"]["items"][0]))
    with pytest.raises(ValueError, match="id"):
        validate_task(t)

    t = _base()
    t["hidden_rubric"]["pass_line"] = 1.5
    with pytest.raises(ValueError, match="pass_line"):
        validate_task(t)


def test_load_tasks_reads_dir_and_reports_bad_file(tmp_path):
    ok = tmp_path / "acc-1.json"
    ok.write_text(json.dumps(_base(), ensure_ascii=False), encoding="utf-8")
    tasks = load_tasks(tmp_path)
    assert len(tasks) == 1 and tasks[0]["id"] == "acc-x"

    bad = tmp_path / "acc-2.json"
    bad.write_text('{"id": "broken"}', encoding="utf-8")
    with pytest.raises(ValueError, match="acc-2"):
        load_tasks(tmp_path)


def test_load_tasks_official_acc001_valid():
    """首批任务数据必须通过校验（真实数据回归）。"""
    root = pathlib.Path(__file__).resolve().parent.parent.parent / "eval" / "accuracy_tasks"
    if not root.exists():
        pytest.skip("accuracy_tasks 尚未建立")
    tasks = load_tasks(root)
    assert any(t["id"] == "acc-001" for t in tasks), tasks
