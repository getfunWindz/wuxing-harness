"""workflow_gen 规则索引生成/对拍守卫（方案 A）。

生成物：`workflow/RULES.md`（按需查阅的规则索引）
源：`workflow/rules.yaml`
"""
from __future__ import annotations

import pathlib

from scripts.workflow_gen import (
    check_rules_doc,
    load_rules,
    render_rules_doc,
    write_rules_doc,
)

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_render_is_deterministic():
    data = load_rules()
    assert render_rules_doc(data) == render_rules_doc(data)


def test_render_contains_all_rule_ids_and_task_types():
    data = load_rules()
    out = render_rules_doc(data)
    for rule in data["rules"]:
        assert f"`{rule['id']}`" in out
        assert rule["must"] in out
    for task in data["task_types"]:
        assert f"`{task['id']}`" in out
        for skill in task["skills"]:
            assert f"`{skill}`" in out


def test_rules_doc_is_current():
    assert check_rules_doc() is None


def test_check_detects_tamper(tmp_path):
    path = tmp_path / "RULES.md"
    path.write_text("# 手改\n", encoding="utf-8")
    diff = check_rules_doc(path)
    assert diff and "手改" in diff


def test_write_roundtrip(tmp_path):
    path = tmp_path / "RULES.md"
    write_rules_doc(path, load_rules())
    assert check_rules_doc(path) is None
