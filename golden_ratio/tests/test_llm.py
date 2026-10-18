from golden_ratio.llm import MockLLM

TASKS = {
    "email": "写一封请假邮件",
    "report": "写一份季度报告",
    "website": "开发一个带用户系统的网站",
    "selection": "分析两款产品并选择一款",
}


def test_mock_returns_shape_json_for_known_task():
    llm = MockLLM()
    raw = llm.shape_task(TASKS["email"])
    assert "nodes" in raw and "edges" in raw and "total_size" in raw
    assert len(raw["nodes"]) == 1


def test_mock_is_deterministic():
    llm = MockLLM()
    assert llm.shape_task(TASKS["report"]) == llm.shape_task(TASKS["report"])


def test_mock_merge_returns_groups_of_node_ids():
    llm = MockLLM()
    nodes = [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}]
    groups = llm.merge_nodes(nodes)
    assert isinstance(groups, list)
    assert all(isinstance(g, list) for g in groups)
    flat = [x for g in groups for x in g]
    assert sorted(flat) == ["n1", "n2", "n3"]


def test_mock_counts_calls_for_cost_metric():
    llm = MockLLM()
    llm.shape_task(TASKS["email"])
    llm.shape_task(TASKS["email"])
    assert llm.call_count == 2


def test_mock_rebalance_suggest_has_moves_field():
    llm = MockLLM()
    out = llm.rebalance_suggest({"node_ids": ["n1"], "low_importance_nodes": ["n2"],
                                 "candidates": [{"fragment_id": "F-0002"}]})
    assert "moves" in out
