from golden_ratio.llm import MockLLM
from golden_ratio.pipeline import run_pipeline


def test_pipeline_fast_path_skips_rebalance():
    llm = MockLLM()
    result = run_pipeline("写一封请假邮件", llm)
    assert result.shape.difficulty == 1
    assert result.shape.fast_path is True
    assert result.rebalance_rounds == 0            # 快路径不触发膨胀
    assert len(result.fragments) == 1
    assert result.fragments[0].key_tokens          # key 已填充


def test_pipeline_full_path_uses_rebalance():
    llm = MockLLM()
    result = run_pipeline("开发一个带用户系统的网站", llm)
    assert result.shape.fast_path is False
    assert result.rebalance_rounds >= 1
    assert len(result.fragments) >= 2


def test_pipeline_all_nodes_covered():
    llm = MockLLM()
    result = run_pipeline("开发一个带用户系统的网站", llm)
    dag = result.dag
    flat = [nid for f in result.fragments for nid in f.node_ids]
    assert sorted(flat) == sorted(n.id for n in dag.nodes)


def test_pipeline_fragments_have_traceable_metadata():
    llm = MockLLM()
    result = run_pipeline("写一份季度报告", llm)
    for f in result.fragments:
        assert f.fragment_id.startswith("F-")
        assert f.stage in ("segment", "rebalance")
        assert isinstance(f.key_tokens, list)


def test_pipeline_rebalance_rounds_bounded():
    llm = MockLLM()
    result = run_pipeline("开发一个带用户系统的网站", llm)
    assert result.rebalance_rounds <= 3             # §3.3 迭代上限 K
