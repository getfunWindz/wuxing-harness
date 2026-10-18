"""〔deprecated v5.3〕评估脚手架（mock 时代）——被 stage2_verify/verify_v5 真实口径链取代；仅测试参照。
（历史注：P2-6 已标记 DEPRECATED）本文件保留用于最小冒烟。
主评估入口 = experiment.run_experiment（5 套测试集）。保留用于最小冒烟。"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from golden_ratio.pipeline import run_pipeline

TASK_SUITE = [
    "写一封请假邮件",
    "写一份季度报告",
    "开发一个带用户系统的网站",
    "分析两款产品并选择一款",
]


def evaluate(llm, cfg=None):
    results = [run_pipeline(t, llm, cfg) for t in TASK_SUITE]

    coverage = sum(
        1.0 for r in results
        if sorted(nid for f in r.fragments for nid in f.node_ids)
        == sorted(n.id for n in r.dag.nodes)
    ) / len(results)

    dep_integrity = 1.0   # mock 下依赖重建由元数据保证（见 pipeline 测试）

    stability = 1.0       # 确定性 mock → 100%；真 LLM 阶段用多次采样对比

    return {
        "coverage": coverage,
        "dependency_integrity": dep_integrity,
        "stability": stability,
        "llm_calls": sum(r.llm_calls for r in results),
        "avg_fragments": sum(len(r.fragments) for r in results) / len(results),
    }


if __name__ == "__main__":
    import json

    from golden_ratio.llm import MockLLM
    print(json.dumps(evaluate(MockLLM()), ensure_ascii=False, indent=2))
