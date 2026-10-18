"""workflow_check C1/C2/C6 守卫（W3.1）。

- C1：rules.yaml schema + L0/L1 完整性
- C2：AGENTS.md 锚点段 vs rules.yaml 渲染对拍
- C6：task_types 结构 + 技能名 kebab-case + 设计 §3.3 ID 集
"""
from __future__ import annotations

import json
import pathlib
import shutil

import yaml

from scripts.workflow_check import CheckResult, main, run_checks

REPO = pathlib.Path(__file__).resolve().parents[2]


def _temp_repo(tmp_path: pathlib.Path, *, tamper_rules_doc: bool = False) -> pathlib.Path:
    (tmp_path / "workflow").mkdir()
    shutil.copy(REPO / "workflow" / "rules.yaml", tmp_path / "workflow" / "rules.yaml")
    if tamper_rules_doc:
        (tmp_path / "workflow" / "RULES.md").write_text(
            "# 手改\n", encoding="utf-8"
        )
    else:
        shutil.copy(REPO / "workflow" / "RULES.md", tmp_path / "workflow" / "RULES.md")
    return tmp_path


def _mutate_rules(repo: pathlib.Path, mutate) -> None:
    path = repo / "workflow" / "rules.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _by_check(results: list[CheckResult]) -> dict[str, CheckResult]:
    return {result.check: result for result in results}


def test_run_checks_ok():
    results = run_checks(REPO)
    assert {r.check for r in results} == {"C1", "C2", "C6"}
    assert all(r.ok for r in results), [r for r in results if not r.ok]


def test_c1_reports_duplicate_rule(tmp_path):
    repo = _temp_repo(tmp_path)

    def mutate(data):
        data["rules"].append(dict(data["rules"][0]))

    _mutate_rules(repo, mutate)
    c1 = _by_check(run_checks(repo))["C1"]
    assert not c1.ok and "重复" in c1.message


def test_c2_reports_tampered_rules_doc(tmp_path):
    repo = _temp_repo(tmp_path, tamper_rules_doc=True)
    c2 = _by_check(run_checks(repo))["C2"]
    assert not c2.ok
    assert "手改" in c2.message


def test_c6_reports_bad_skill_name(tmp_path):
    repo = _temp_repo(tmp_path)

    def mutate(data):
        data["task_types"][0]["skills"] = ["Bad_Skill"]

    _mutate_rules(repo, mutate)
    c6 = _by_check(run_checks(repo))["C6"]
    assert not c6.ok and "kebab-case" in c6.message


def test_c6_reports_unknown_task_type(tmp_path):
    repo = _temp_repo(tmp_path)

    def mutate(data):
        data["task_types"].append(
            {"id": "unknown", "scene": "x", "skills": [], "evidence": "E-x"}
        )

    _mutate_rules(repo, mutate)
    c6 = _by_check(run_checks(repo))["C6"]
    assert not c6.ok and "§3.3" in c6.message


def test_cli_json(capsys):
    assert main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert {item["check"] for item in payload["checks"]} == {"C1", "C2", "C6"}


def test_cli_human(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "[workflow_check] C1" in out
    assert "[workflow_check] OK" in out


def test_ci_check_includes_workflow_gate():
    from scripts.ci_check import CHECKS

    assert any(
        "workflow_check" in " ".join(cmd) for _, cmd in CHECKS
    ), "ci_check 未接入 workflow_check"
