"""TDD：速度测试——expert 宽首轮结构 + 单轮并发统计。"""
import json
import pathlib
import tempfile


def test_expert_first_turn_is_wide_batch():
    """首轮 = 宽任务（一次注入多个独立子交付物）——单轮即测并发上限。"""
    from wuxing.real_test import PROFILES
    first = PROFILES["expert"]["turns"][0]["text"]
    assert len(first) > 200
    for k in ("背景", "技术栈", "模块", "验收"):
        assert k in first, f"保留画像关键词：{k}"
    assert "独立子模块" in first, "宽任务必须明示「独立子模块」（单轮测并发）"
    assert first.count("①") + first.count("②") + first.count("③") >= 5, \
        "宽首轮需一次列出多个独立交付项（≥5）"


def test_run_profile_speed_stats_fields():
    """轮级报告含单轮速度结构：单元数 / 最大并发 / 最长单元墙钟。"""
    from wuxing.real_test import run_profile
    wd = pathlib.Path(tempfile.mkdtemp())
    run_profile("precise", workdir=wd, llm=None, real_shape=False, max_turns=1)
    payload = json.loads((wd / "real_test_report.json").read_text(encoding="utf-8"))
    row = payload["turns"][0]
    for k in ("unit_count", "max_concurrency", "longest_unit_s"):
        assert k in row, k
    assert "speed" in payload["summary"], "摘要必须含并发/时长汇总"
