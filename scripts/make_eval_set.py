"""L1-2：从真实任务套件生成评测集（元数据化——知识库「从真实任务出发」标准）。

确定性：seed 固定抽样（可复现）；元数据从套件既有字段推导：
  difficulty    ← human_difficulty（缺失 → "unknown"）
  expected_kinds ← dag_spec 节点 domain 聚合（plan→plan / execute→result / verify→verdict）
  suite/source  ← 套件名 + 原文 id（溯源）
产出：eval/tasks.v1.json（{version, created, tasks[]}）。
"""
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wuxing.router import route_fragment

SUITES = ["calibration_tasks", "mega_tasks", "professional_tasks",
          "domain_tasks", "github_tasks"]

_DOMAIN_KIND = {"plan": "plan", "execute": "result", "verify": "verdict"}


def build_eval_set(n_per_suite: int = 4, seed: int = 42) -> dict:
    tasks = []
    rng = random.Random(seed)
    for suite in SUITES:
        raw = json.loads(
            (pathlib.Path("golden_ratio/data") / f"{suite}.json").read_text(
                encoding="utf-8"))["tasks"]
        rng.shuffle(raw)
        for t in raw[:n_per_suite]:
            # expected_kinds：节点文本经引擎确定性路由（开放标签→封闭域）
            dag = t.get("dag_spec") or {}
            nodes = dag.get("nodes", []) if isinstance(dag, dict) else []
            domains = {route_fragment(str(n.get("text", "")))
                       for n in nodes if str(n.get("text", ""))}
            expected = sorted({_DOMAIN_KIND.get(d, "result")
                               for d in domains if d in _DOMAIN_KIND})
            tasks.append({
                "id": f"{suite[:3]}-{t.get('id', str(len(tasks) + 1))}",
                "task_text": t["task_text"],
                "suite": suite,
                "difficulty": t.get("human_difficulty", "unknown"),
                # github 套件无预成型 DAG（issue 原文）——expected 诚实置空不猜
                "expected_kinds": expected,
                "acceptance_notes": ("验收要点：任务完整闭环（plan/execute/verify 收敛，"
                                     "产物真实存在且与任务目标一致）"
                                     if expected else
                                     "验收要点：基础闭环（无预成型 DAG——按任务语义执行并收口）"),
                "source": t.get("source", suite),
            })
    return {"version": "v1", "created": "2026-09-06",
            "method": "seed=42 均衡抽样；元数据从套件字段 + 引擎路由推导", "tasks": tasks}


if __name__ == "__main__":
    import sys
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "eval/tasks.v1.json")
    data = build_eval_set()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written {out} ({len(data['tasks'])} tasks)")
