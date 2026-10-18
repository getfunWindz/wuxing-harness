"""〔deprecated v5.3〕流水线编排（修订稿 §7，mock 入口）——真实口径链走 experiment._run_task/stage2；保留作测试入口。"""
from dataclasses import dataclass, field

from golden_ratio.keyify import extract_keys
from golden_ratio.rebalance import rebalance
from golden_ratio.segment import segment
from golden_ratio.shape import shape_task


@dataclass
class PipelineResult:
    dag: object
    shape: object
    fragments: list = field(default_factory=list)
    rebalance_rounds: int = 0
    llm_calls: int = 0


def run_pipeline(task_text, llm, cfg=None):
    dag, shape = shape_task(task_text, llm, cfg)
    fragments = segment(dag, shape, llm, cfg, task_text=task_text)

    rounds = 0
    if not shape.fast_path:
        fragments, rounds = rebalance(fragments, dag, cfg, shape)

    # 碎片文本与 key
    node_text = {n.id: n.text for n in dag.nodes}
    for f in fragments:
        f.text = " ".join(node_text[nid] for nid in f.node_ids)
        f.key_tokens = extract_keys(f.text, cfg)

    return PipelineResult(dag=dag, shape=shape, fragments=fragments,
                          rebalance_rounds=rounds, llm_calls=llm.call_count)
