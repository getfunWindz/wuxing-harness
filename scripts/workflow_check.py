"""工作流校验器（W3.1）：C1 schema / C2 生成物对拍 / C6 task_types 自洽。

用法：
  python -m scripts.workflow_check          # 人类摘要；错误 exit 1
  python -m scripts.workflow_check --json   # 机器消费
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib

from scripts.workflow_gen import (
    WorkflowError,
    check_rules_doc,
    load_rules_data,
    validate_rules,
    validate_task_types,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


@dataclasses.dataclass(frozen=True)
class CheckResult:
    check: str
    ok: bool
    summary: str
    message: str = ""


def _check_c1(rules_path: pathlib.Path) -> tuple[CheckResult, dict | None]:
    try:
        data = load_rules_data(rules_path)
    except WorkflowError as exc:
        return CheckResult("C1", False, "rules.yaml schema", str(exc)), None
    errors = validate_rules(data)
    if errors:
        return (
            CheckResult("C1", False, "rules.yaml schema", "\n".join(errors)),
            data,
        )
    return CheckResult("C1", True, "rules.yaml schema"), data


def _check_c2(
    repo_root: pathlib.Path, data: dict | None, c1_ok: bool
) -> CheckResult:
    if data is None:
        return CheckResult("C2", False, "规则索引对拍", "C1 失败，跳过对拍")
    if not c1_ok:
        return CheckResult("C2", False, "规则索引对拍", "C1 失败，跳过对拍")
    target = repo_root / "workflow" / "RULES.md"
    if not target.exists():
        return CheckResult("C2", False, "规则索引对拍", "未找到 workflow/RULES.md")
    try:
        diff = check_rules_doc(target, data)
    except WorkflowError as exc:
        return CheckResult("C2", False, "规则索引对拍", str(exc))
    if diff:
        return CheckResult(
            "C2", False, "规则索引对拍", f"{target} 漂移：\n{diff}"
        )
    return CheckResult("C2", True, "规则索引对拍")


def _check_c6(data: dict | None) -> CheckResult:
    if data is None:
        return CheckResult("C6", False, "task_types 自洽", "YAML 解析失败，跳过 C6")
    errors = validate_task_types(data.get("task_types") if isinstance(data, dict) else None)
    return CheckResult("C6", not errors, "task_types 自洽", "\n".join(errors))


def run_checks(repo_root: pathlib.Path = REPO_ROOT) -> list[CheckResult]:
    """运行 C1/C2/C6；返回逐项结果（不抛异常）。"""
    repo_root = pathlib.Path(repo_root)
    c1, data = _check_c1(repo_root / "workflow" / "rules.yaml")
    return [c1, _check_c2(repo_root, data, c1.ok), _check_c6(data)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="工作流校验 C1/C2/C6")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    results = run_checks()
    ok = all(result.ok for result in results)

    if args.json:
        print(json.dumps(
            {
                "ok": ok,
                "checks": [dataclasses.asdict(result) for result in results],
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0 if ok else 1

    for result in results:
        status = "OK" if result.ok else "FAIL"
        print(f"[workflow_check] {result.check} {result.summary} ... {status}")
        if not result.ok and result.message:
            for line in result.message.splitlines():
                print(f"  {line}")
    print("[workflow_check] OK" if ok else "[workflow_check] FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
