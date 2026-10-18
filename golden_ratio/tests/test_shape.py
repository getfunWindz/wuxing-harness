from golden_ratio.llm import MockLLM
from golden_ratio.shape import shape_task


def test_shape_email_task():
    dag, shape = shape_task("写一封请假邮件", MockLLM())
    assert len(dag.nodes) == 1
    assert shape.fast_path is True
    assert shape.difficulty == 1


def test_shape_website_task_is_full_path():
    dag, shape = shape_task("开发一个带用户系统的网站", MockLLM())
    assert len(dag.nodes) == 6
    assert shape.fast_path is False
    assert shape.difficulty >= 3


def test_shape_dag_connected_after_validation():
    dag, _ = shape_task("写一份季度报告", MockLLM())
    assert {n.id for n in dag.nodes} == {"n1", "n2", "n3"}


def test_shape_domain_dist_aggregated():
    _, shape = shape_task("写一份季度报告", MockLLM())
    assert "写作" in shape.domain_dist
    assert abs(sum(shape.domain_dist.values()) - 1.0) < 0.01
