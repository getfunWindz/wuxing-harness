"""评测集（L1-2 · 元数据化——知识库「从真实任务出发」标准落地）。

数据：eval/tasks.v1.json（scripts/make_eval_set.py 确定性生成——真实任务 + 元数据）。
每任务字段：id / task_text / suite / difficulty / expected_kinds /
acceptance_notes / source——元数据不完整即 ValueError（评测集引用质量铁律）。
"""
import json
import pathlib

REQUIRED_FIELDS = {"id", "task_text", "suite", "difficulty", "expected_kinds",
                   "acceptance_notes", "source"}

DEFAULT_PATH = (pathlib.Path(__file__).resolve().parent / ".." / "eval"
                / "tasks.v1.json")


def load_eval_tasks(path: pathlib.Path | str | None = None) -> list:
    """加载评测集（字段完整性校验——缺字段 ValueError；损坏 JSON ValueError）。"""
    p = pathlib.Path(path) if path else DEFAULT_PATH
    if not p.exists():
        raise ValueError(f"评测集不存在：{p}（先运行 scripts/make_eval_set.py）")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"评测集损坏：{p}（{e}）") from e
    tasks = data.get("tasks", [])
    if not tasks or not isinstance(tasks, list):
        raise ValueError(f"评测集无任务：{p}")
    for t in tasks:
        missing = REQUIRED_FIELDS - set(t)
        if missing:
            raise ValueError(f"评测任务缺字段 {sorted(missing)}：{t.get('id', '?')}")
    return tasks


def eval_set_summary(tasks: list) -> dict:
    """套件/难度分布摘要（评测集健康状况——覆盖不失真）。"""
    suites, diffs = {}, {}
    for t in tasks:
        suites[t["suite"]] = suites.get(t["suite"], 0) + 1
        d = t.get("difficulty", "unknown")
        diffs[d] = diffs.get(d, 0) + 1
    return {"total": len(tasks), "suites": suites, "difficulties": diffs}
