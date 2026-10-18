"""工作流规则单一来源守卫（W3.1）。

`workflow/rules.yaml` 是规则 / 任务类型 / 技能映射的单一来源；本文件锁定：
- schema 必填字段 / 未知字段拒绝 / ID 唯一；
- L0/L1 ID 集与设计 §2.3/§2.4 完全一致；
- task_types 与设计 §3.3 完全一致；
- 技能名 kebab-case。
"""
from __future__ import annotations

import pathlib
import re

import pytest

from scripts.workflow_gen import (
    CANONICAL_L0_IDS,
    CANONICAL_L1_IDS,
    CANONICAL_TASK_TYPES,
    WorkflowError,
    load_rules,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
RULES = REPO / "workflow" / "rules.yaml"
DESIGN = REPO / "docs" / "WUXING_工作流系统设计_v0.1.md"

RULE_REQUIRED = (
    "id", "level", "domain", "scope", "trigger",
    "must", "evidence", "owner", "source",
)
TASK_REQUIRED = ("id", "scene", "skills", "evidence")


def _mutated_rules(tmp_path: pathlib.Path, mutate) -> pathlib.Path:
    import yaml

    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "rules.yaml"
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_rules_yaml_loads_and_validates():
    data = load_rules(RULES)
    assert data["version"] == 1
    assert len(data["rules"]) >= 15
    assert len(data["task_types"]) == len(CANONICAL_TASK_TYPES)


def test_rules_have_required_fields():
    data = load_rules(RULES)
    for rule in data["rules"]:
        for field in RULE_REQUIRED:
            assert rule.get(field), f"{rule.get('id')} 缺字段 {field}"
        assert isinstance(rule["domain"], list) and rule["domain"]
        assert isinstance(rule["scope"], list) and rule["scope"]
        assert isinstance(rule["evidence"], list) and rule["evidence"]


def test_l0_l1_ids_exactly_match_canonical():
    data = load_rules(RULES)
    by_level: dict[str, set[str]] = {}
    for rule in data["rules"]:
        by_level.setdefault(rule["level"], set()).add(rule["id"])
    assert by_level["L0"] == CANONICAL_L0_IDS
    assert by_level["L1"] == CANONICAL_L1_IDS


def test_task_types_exactly_match_canonical():
    data = load_rules(RULES)
    assert {t["id"] for t in data["task_types"]} == CANONICAL_TASK_TYPES
    for task in data["task_types"]:
        for field in TASK_REQUIRED:
            assert task.get(field) is not None, f"{task.get('id')} 缺字段 {field}"


def test_skill_names_are_kebab_case():
    data = load_rules(RULES)
    pattern = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
    for task in data["task_types"]:
        for skill in task["skills"]:
            assert pattern.match(skill), f"{task['id']} 技能名非 kebab-case：{skill}"


def test_duplicate_rule_id_rejected(tmp_path):
    def mutate(data):
        data["rules"].append(dict(data["rules"][0]))

    with pytest.raises(WorkflowError, match="重复"):
        load_rules(_mutated_rules(tmp_path, mutate))


def test_unknown_rule_field_rejected(tmp_path):
    def mutate(data):
        data["rules"][0]["unexpected"] = "x"

    with pytest.raises(WorkflowError, match="未知字段"):
        load_rules(_mutated_rules(tmp_path, mutate))


def test_missing_source_rejected(tmp_path):
    def mutate(data):
        data["rules"][0].pop("source", None)

    with pytest.raises(WorkflowError, match="source"):
        load_rules(_mutated_rules(tmp_path, mutate))


def test_invalid_level_rejected(tmp_path):
    def mutate(data):
        data["rules"][0]["level"] = "L9"

    with pytest.raises(WorkflowError, match="level"):
        load_rules(_mutated_rules(tmp_path, mutate))


def test_canonical_ids_match_design_doc():
    if not DESIGN.exists():
        pytest.skip("公开树无设计文档")
    text = DESIGN.read_text(encoding="utf-8")
    l0 = set(re.findall(r"^\|\s*(L0-[A-Z0-9]+-\d+)\s*\|", text, re.MULTILINE))
    l1 = set(re.findall(r"^\|\s*(L1-[A-Z0-9]+-\d+)\s*\|", text, re.MULTILINE))
    assert l0 == CANONICAL_L0_IDS
    assert l1 == CANONICAL_L1_IDS


def test_task_types_match_design_doc():
    if not DESIGN.exists():
        pytest.skip("公开树无设计文档")
    text = DESIGN.read_text(encoding="utf-8")
    ids = set(
        re.findall(
            r"^\|\s*(bug|implement|multi_step|feature_design|doc_writing|"
            r"research|review|review_received|merge|isolation)\s*\|",
            text,
            re.MULTILINE,
        )
    )
    assert ids == CANONICAL_TASK_TYPES
