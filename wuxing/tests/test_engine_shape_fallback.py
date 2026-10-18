import pathlib
import tempfile

from wuxing.engine import Engine


def test_engine_survives_shape_failure():
    """边界回归（S6 更新）：形状化失败（重试耗尽/校验失败）→ 兜底单碎片执行
    （不再全败——真实测试 expert-2 教训；报告标注兜底）。"""
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    # 注入形状化失败
    def boom(task_text):
        raise ValueError("形状化输出两次均非法")
    eng._build_fragments = boom
    result = eng.run_task("写一封请假邮件")
    assert result.status in ("done", "partial", "failed"), "兜底后必须有结果"
    assert result.fragments, "兜底必须构造碎片（不再空碎片全败）"
    assert "形状化兜底" in result.report


def test_shape_validation_failure_falls_back(tmp_path=None):
    """S6（真实测试 expert-2 暴露）：形状化校验失败（DAG 不连通——叮嘱类文本）
    → 兜底单碎片执行（不再任务全败——快准省的「准」）。"""
    import pathlib
    import tempfile
    from unittest import mock

    from wuxing.config import EngineConfig
    from wuxing.engine import Engine

    wd = pathlib.Path(tmp_path or tempfile.mkdtemp())
    eng = Engine(cfg=EngineConfig(), workdir=wd, auto_confirm=True)
    # 先用 mock 形状化跑一次拿基线（应成功）——再让 shape_task 抛校验错误
    with mock.patch("golden_ratio.shape.shape_task",
                    side_effect=ValueError("形状化结果不合法: 孤立节点")):
        res = eng.run_task("开始实现时注意分层推进：先脚手架，再通用层，最后聚合。")
    assert res.status in ("done", "partial", "failed"), "兜底后必须有任务结果"
    assert res.fragments, "兜底必须构造碎片（单碎片 fallback）"
    assert any(f.get("_shape_fallback") for f in res.fragments), \
        "兜底碎片必须带标记（透明归因）"
    assert "形状化兜底" in res.report, "报告必须标注兜底（透明）"
