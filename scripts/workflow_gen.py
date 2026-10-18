"""工作流规则单一来源：加载与 schema 校验（W3.1）。

数据源：`workflow/rules.yaml`
生成物：`AGENTS.md` / `public/AGENTS.md` 的锚点段（渲染见后续版本）
用法：
  python -m scripts.workflow_gen            # 写入锚点段
  python -m scripts.workflow_gen --check    # 对拍（CI/本地门禁）
"""
from __future__ import annotations

import argparse
import difflib
import pathlib
import re
import sys
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES_PATH = REPO_ROOT / "workflow" / "rules.yaml"
RULES_DOC = REPO_ROOT / "workflow" / "RULES.md"


class WorkflowError(Exception):
    """rules.yaml 结构 / 内容错误（消息可读，CLI 直接展示）。"""


# 与 docs/WUXING_工作流系统设计_v0.1.md §2.3 / §2.4 对齐的机器锚点。
# 公开树没有 docs/，因此校验器使用本常量；私有树由测试对设计文档反向核对。
CANONICAL_L0_IDS = frozenset({
    "L0-SEC-1",
    "L0-TRUTH-1",
    "L0-USER-1",
    "L0-PHIL-1",
})
CANONICAL_L1_IDS = frozenset({
    "L1-TDD-1",
    "L1-BUG-1",
    "L1-EVID-1",
    "L1-PLAN-1",
    "L1-REG-1",
    "L1-MOUSE-1",
    "L1-COMMIT-1",
    "L1-DOC-1",
    "L1-READ-1",
    "L1-FREEZE-1",
    "L1-ORIG-1",
})
# 与设计 §3.3 task_types 表对齐。
CANONICAL_TASK_TYPES = frozenset({
    "bug",
    "implement",
    "multi_step",
    "feature_design",
    "doc_writing",
    "research",
    "review",
    "merge",
    "review_received",
    "isolation",
})

RULE_FIELDS = frozenset({
    "id", "level", "domain", "scope", "trigger", "must",
    "evidence", "owner", "source", "exception",
})
TASK_TYPE_FIELDS = frozenset({"id", "scene", "skills", "evidence", "note"})
LEVELS = frozenset({"L0", "L1", "L2", "L3"})
DOMAINS = frozenset({"all", "plan", "execute", "verify", "user", "repo"})
RULE_ID_RE = re.compile(r"^(L[0-3])-[A-Z0-9]+-\d+$")
KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_str_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_is_nonempty_str(item) for item in value)
    )


def _validate_task_types(task_types: Any, errors: list[str]) -> set[str]:
    if not isinstance(task_types, list) or not task_types:
        errors.append("task_types 必须是非空列表")
        return set()

    ids: set[str] = set()
    for index, task in enumerate(task_types):
        where = f"task_types[{index}]"
        if not isinstance(task, dict):
            errors.append(f"{where}: 必须是映射")
            continue
        task_id = task.get("id", "?")
        where = f"{where} ({task_id})"

        unknown = set(task) - TASK_TYPE_FIELDS
        if unknown:
            errors.append(f"{where}: 未知字段 {sorted(unknown)}")
        for field in ("id", "scene", "skills", "evidence"):
            if field not in task:
                errors.append(f"{where}: 缺字段 {field}")
        if not _is_nonempty_str(task.get("id")):
            errors.append(f"{where}: id 必须是非空字符串")
            continue
        if task["id"] in ids:
            errors.append(f"{where}: task_type id 重复")
        ids.add(task["id"])
        if not _is_nonempty_str(task.get("scene")):
            errors.append(f"{where}: scene 必须是非空字符串")
        skills = task.get("skills")
        if not isinstance(skills, list):
            errors.append(f"{where}: skills 必须是列表（可为空）")
        else:
            for skill in skills:
                if not _is_nonempty_str(skill) or not KEBAB_RE.match(skill):
                    errors.append(f"{where}: 技能名非 kebab-case：{skill!r}")
        if not _is_nonempty_str(task.get("evidence")):
            errors.append(f"{where}: evidence 必须是非空字符串")
        if "note" in task and not _is_nonempty_str(task["note"]):
            errors.append(f"{where}: note 必须是非空字符串")

    if ids != CANONICAL_TASK_TYPES:
        missing = sorted(CANONICAL_TASK_TYPES - ids)
        extra = sorted(ids - CANONICAL_TASK_TYPES)
        errors.append(
            "task_types ID 集与设计 §3.3 不一致"
            f"（缺 {missing} / 多 {extra}）"
        )
    return ids


def validate_task_types(task_types: Any) -> list[str]:
    """独立校验 task_types（供 workflow_check C6 使用）。"""
    errors: list[str] = []
    _validate_task_types(task_types, errors)
    return errors


def validate_rules(data: Any) -> list[str]:
    """校验 rules.yaml 结构；返回错误列表（空 = 通过）。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["rules.yaml 顶层必须是映射"]

    if data.get("version") != 1:
        errors.append("version 必须是 1")

    task_types = data.get("task_types")
    task_ids = _validate_task_types(task_types, errors)

    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        errors.append("rules 必须是非空列表")
        return errors

    seen: set[str] = set()
    by_level: dict[str, set[str]] = {}
    for index, rule in enumerate(rules):
        where = f"rules[{index}]"
        if not isinstance(rule, dict):
            errors.append(f"{where}: 必须是映射")
            continue
        rule_id = rule.get("id", "?")
        where = f"{where} ({rule_id})"

        unknown = set(rule) - RULE_FIELDS
        if unknown:
            errors.append(f"{where}: 未知字段 {sorted(unknown)}")
        for field in ("id", "level", "domain", "scope", "trigger",
                      "must", "evidence", "owner", "source"):
            if field not in rule:
                errors.append(f"{where}: 缺字段 {field}")

        if not _is_nonempty_str(rule.get("id")):
            errors.append(f"{where}: id 必须是非空字符串")
            continue
        rule_id = rule["id"]
        if not RULE_ID_RE.match(rule_id):
            errors.append(f"{where}: id 形态非法（应为 L0-L3-NAME-N）")
        if rule_id in seen:
            errors.append(f"{where}: 规则 id 重复")
        seen.add(rule_id)

        level = rule.get("level")
        if level not in LEVELS:
            errors.append(f"{where}: level 非法（{level!r}）")
        elif RULE_ID_RE.match(rule_id) and rule_id.split("-")[0] != level:
            errors.append(f"{where}: level 与 id 前缀不一致")
        if isinstance(level, str):
            by_level.setdefault(level, set()).add(rule_id)

        domain = rule.get("domain")
        if not _is_str_list(domain):
            errors.append(f"{where}: domain 必须是非空字符串列表")
        else:
            bad = sorted(set(domain) - DOMAINS)
            if bad:
                errors.append(f"{where}: domain 含未知值 {bad}")

        scope = rule.get("scope")
        if not _is_str_list(scope):
            errors.append(f"{where}: scope 必须是非空字符串列表")
        else:
            bad = sorted(set(scope) - task_ids - {"all"})
            if bad:
                errors.append(f"{where}: scope 含未知 task_type {bad}")

        for field in ("trigger", "must", "owner", "source"):
            if not _is_nonempty_str(rule.get(field)):
                errors.append(f"{where}: {field} 必须是非空字符串")
        if not _is_str_list(rule.get("evidence")):
            errors.append(f"{where}: evidence 必须是非空字符串列表")
        if "exception" in rule and not _is_nonempty_str(rule["exception"]):
            errors.append(f"{where}: exception 必须是非空字符串")

    if by_level.get("L0", set()) != CANONICAL_L0_IDS:
        errors.append(
            "L0 ID 集与设计 §2.3 不一致"
            f"（缺 {sorted(CANONICAL_L0_IDS - by_level.get('L0', set()))}"
            f" / 多 {sorted(by_level.get('L0', set()) - CANONICAL_L0_IDS)}）"
        )
    if by_level.get("L1", set()) != CANONICAL_L1_IDS:
        errors.append(
            "L1 ID 集与设计 §2.4 不一致"
            f"（缺 {sorted(CANONICAL_L1_IDS - by_level.get('L1', set()))}"
            f" / 多 {sorted(by_level.get('L1', set()) - CANONICAL_L1_IDS)}）"
        )

    return errors


def load_rules_data(path: pathlib.Path = RULES_PATH) -> Any:
    """只做 YAML 解析（不校验），供 C6 在 schema 失败时仍能报告 task_types 问题。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkflowError(f"无法读取 {path}：{exc}") from exc
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise WorkflowError(f"{path} YAML 解析失败：{exc}") from exc


def load_rules(path: pathlib.Path = RULES_PATH) -> dict:
    """读取并校验 rules.yaml；失败抛 WorkflowError（附全部错误）。"""
    data = load_rules_data(path)
    errors = validate_rules(data)
    if errors:
        raise WorkflowError(
            f"{path} 校验失败：\n- " + "\n- ".join(errors)
        )
    return data


def render_rules_doc(data: dict) -> str:
    """把 rules.yaml 渲染为 workflow/RULES.md（确定性、无时间戳）。"""
    lines = [
        "# WUXING 工作流规则索引",
        "",
        (
            "> 本文件由 `workflow/rules.yaml` 生成——禁手改；"
            "更新：`python -m scripts.workflow_gen`；"
            "对拍：`python -m scripts.workflow_gen --check`。"
        ),
        "> 本文件是**按需查阅**的规则索引；每任务必读的精炼手册是根 `AGENTS.md`。",
        "",
        "## 任务类型 → 流程技能",
        "",
        "| id | 场景 | 技能链 | 证据合同 |",
        "|---|---|---|---|",
    ]
    for task in data["task_types"]:
        skills = " + ".join(f"`{name}`" for name in task["skills"]) or "—"
        lines.append(
            f"| `{task['id']}` | {task['scene']} | {skills} | `{task['evidence']}` |"
        )

    lines.extend(["", "## 规则速查", ""])
    level_names = {
        "L0": "L0 · 不可违背",
        "L1": "L1 · 工程铁律",
        "L2": "L2 · 项目约定",
        "L3": "L3 · 建议",
    }
    for level, title in level_names.items():
        rules = [rule for rule in data["rules"] if rule["level"] == level]
        if not rules:
            continue
        lines.extend([f"### {title}", ""])
        for rule in rules:
            scope = ", ".join(rule["scope"])
            evidence = " + ".join(rule["evidence"])
            lines.append(
                f"- **`{rule['id']}`**（{scope}）"
                f"触发：{rule['trigger']}；必须：{rule['must']}；证据：{evidence}"
            )
        lines.append("")

    if lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def normalize(text: str) -> str:
    """对拍口径：统一换行、去行尾空白、去首尾空行。"""
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in raw.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def check_rules_doc(path: pathlib.Path = RULES_DOC,
                    data: dict | None = None) -> str | None:
    """对拍 workflow/RULES.md；一致返回 None，否则返回 unified diff。"""
    data = data or load_rules()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkflowError(f"无法读取 {path}：{exc}") from exc
    expected = render_rules_doc(data)
    if normalize(text) == normalize(expected):
        return None
    diff = difflib.unified_diff(
        normalize(text).splitlines(),
        normalize(expected).splitlines(),
        fromfile=f"{path} (current)",
        tofile="workflow_gen (expected)",
        lineterm="",
    )
    return "\n".join(diff)


def write_rules_doc(path: pathlib.Path = RULES_DOC,
                    data: dict | None = None) -> None:
    """写入 workflow/RULES.md（整文件生成）。"""
    data = data or load_rules()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_rules_doc(data), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="工作流规则索引生成/对拍")
    parser.add_argument("--check", action="store_true", help="只对拍，不写入")
    args = parser.parse_args(argv)
    try:
        data = load_rules()
    except WorkflowError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.check:
        try:
            diff = check_rules_doc(RULES_DOC, data)
        except WorkflowError as exc:
            print(f"[workflow_gen] {exc}", file=sys.stderr)
            return 1
        if diff:
            print(f"[workflow_gen] {RULES_DOC} 漂移：\n{diff}", file=sys.stderr)
            return 1
        print("[workflow_gen] 对拍通过（workflow/RULES.md）")
        return 0

    try:
        write_rules_doc(RULES_DOC, data)
    except WorkflowError as exc:
        print(f"[workflow_gen] {exc}", file=sys.stderr)
        return 1
    print("[workflow_gen] 已写入 workflow/RULES.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
