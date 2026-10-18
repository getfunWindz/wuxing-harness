"""任务形状化（修订稿 §3.1）：LLM 原始输出 → 结构校验 → 规范化 → DAG + Shape。

接入 validate_shape_output（降成本方案 #2）：输出必须先过结构校验（字段齐全/
DAG 连通/无环/id 唯一），合法即信任单次输出；非法重试一次，仍非法抛 ValueError。
"""
from golden_ratio.difficulty import compute_shape
from golden_ratio.models import DAG, Node
from golden_ratio.validate import validate_shape_output


def _parse(raw, cfg):
    nodes, edges = [], []
    for nd in raw["nodes"]:
        nodes.append(Node(
            id=nd["id"], text=nd["text"],
            domain_dist=dict(nd["domain_dist"]),
            trades=list(nd["trades"]),
            complexity=nd["complexity"],
            color_weight=float(nd["color_weight"]),
            deliverable=nd["deliverable"],
        ))
    for a, b in raw["edges"]:
        edges.append((a, b))
    dag = DAG(nodes=nodes, edges=edges)
    shape = compute_shape(dag, cfg)
    return dag, shape


def shape_task(task_text, llm, cfg=None):
    if cfg is None:
        from golden_ratio.config import AlgorithmConfig
        cfg = AlgorithmConfig()
    raw = llm.shape_task(task_text)
    ok, norm, errs = validate_shape_output(raw)
    if not ok:
        # 约束：结构非法视为解析失败，重试一次（§3.1；含空 DAG/连通性/无环/id 唯一）
        raw = llm.shape_task(task_text)
        ok, norm, errs = validate_shape_output(raw)
        if not ok:
            raise ValueError(f"形状化输出两次均非法: {errs}")
    dag, shape = _parse(norm, cfg)
    return dag, shape
