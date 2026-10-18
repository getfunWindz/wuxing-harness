"""112 套件回归评估（P7：路由/域分配质量——规格书 §13 域定案的数据来源）。

数据源：golden_ratio/data/real_shape_outputs.json（112 任务真实形状化 DAG，零 LLM 成本）。
流程：每任务 dag_spec → 节点文本 → route_fragment → 域分配统计。
"""
import json
import pathlib

from wuxing.router import route_fragment

DATA = pathlib.Path(__file__).resolve().parent / ".." / "golden_ratio" / "data" / "real_shape_outputs.json"

def load_112_tasks() -> list:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    tasks = data["tasks"]
    return [t for t in (list(tasks.values()) if isinstance(tasks, dict) else tasks)
            if t.get("ok") and t.get("suite") != "github_tasks.json"]

def load_github_tasks() -> list:
    """P8：github 套件任务（真形状化，预算放开后 208 条）。"""
    data = json.loads(DATA.read_text(encoding="utf-8"))
    tasks = data["tasks"]
    return [t for t in (list(tasks.values()) if isinstance(tasks, dict) else tasks)
            if t.get("ok") and t.get("suite") == "github_tasks.json"]

def load_all_tasks() -> list:
    return load_112_tasks() + load_github_tasks()

def _node_texts(task) -> list:
    """从 dag_spec 提取节点文本（golden_ratio 结构：nodes: [{id, text, ...}]）。"""
    spec = task.get("dag_spec", {})
    nodes = spec.get("nodes", []) if isinstance(spec, dict) else []
    return [n.get("text", "") for n in nodes]

def eval_route_quality(tasks: list) -> dict:
    import collections
    dist = collections.Counter()
    verify_tasks = 0
    three_chain = 0
    for t in tasks:
        texts = _node_texts(t)
        domains = {route_fragment(x) for x in texts if x}
        for d in domains:
            dist[d] += 1
        if "verify" in domains:
            verify_tasks += 1
        if {"plan", "execute", "verify"} <= domains:
            three_chain += 1
    total = len(tasks)
    return {
        "total": total,
        "domain_dist": dict(dist),
        "verify_coverage": round(verify_tasks / total, 3) if total else 0.0,
        "three_chain_rate": round(three_chain / total, 3) if total else 0.0,
    }

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true", help="JSON 输出")
    p.add_argument("--github", action="store_true", help="仅 github 套件")
    args = p.parse_args()
    if args.github:
        tasks = load_github_tasks()
    else:
        tasks = load_all_tasks()  # 全套件（原 112 + github 208）
    report = eval_route_quality(tasks)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"总任务: {report['total']}")
        print(f"域分布: {report['domain_dist']}")
        print(f"verify 覆盖: {report['verify_coverage']}")
        print(f"三链率: {report['three_chain_rate']}")
