"""TDD（P0-2 B）：拆分质量观察指标——机械可算（域分布/重叠峰值/verify 构造信号）。"""


def test_shape_quality_metrics_and_note():
    from wuxing.engine import _shape_quality, _shape_quality_note
    frags = [
        {"fragment_id": "F-1", "domain": "execute",
         "text": "实现 csv_clean.py：读取 raw.csv 跳过空行并去重写出 clean.csv"},
        {"fragment_id": "F-2", "domain": "execute",
         "text": "实现 csv_clean.py：读取 raw.csv 跳过空行并去重写出 clean.csv 并测试"},
        {"fragment_id": "F-3", "domain": "verify",
         "text": "编写 test_csv_clean.py 覆盖空文件场景"},
    ]
    sq = _shape_quality(frags)
    assert sq["nodes"] == 3
    assert sq["domain_dist"] == {"execute": 2, "verify": 1}
    assert sq["text_overlap_max"] > 0.6           # F-1/F-2 高度重叠
    assert set(sq["text_overlap_pair"]) == {"F-1", "F-2"}
    assert sq["verify_construction"] == 1          # verify 域含「编写」
    note = _shape_quality_note(sq)
    assert "[拆分质量]" in note and "重叠" in note and "verify 构造" in note


def test_shape_quality_clean_split_no_note():
    from wuxing.engine import _shape_quality, _shape_quality_note
    frags = [
        {"fragment_id": "F-1", "domain": "plan", "text": "制定实施方案"},
        {"fragment_id": "F-2", "domain": "execute", "text": "实现主功能"},
        {"fragment_id": "F-3", "domain": "verify", "text": "验收主功能"},
    ]
    sq = _shape_quality(frags)
    assert sq["text_overlap_max"] < 0.6
    assert sq["verify_construction"] == 0
    assert _shape_quality_note(sq) == ""


def test_shape_quality_trace_event_on_build(tmp_path):
    """引擎集成：形状化构建发出 shape_quality trace 事件（观测原料）。"""
    import json
    import pathlib

    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    eng = Engine(workdir=pathlib.Path(tmp_path),
                 cfg=EngineConfig(use_real_shape=False))
    frags = eng._build_fragments("创建 hello.txt 并写入 hello")
    assert frags
    rows = [json.loads(line) for line in
            (pathlib.Path(tmp_path) / ".wuxing" / "trace.jsonl")
            .read_text(encoding="utf-8").splitlines() if line.strip()]
    ev = [r for r in rows if r.get("event") == "shape_quality"]
    assert ev and ev[-1].get("nodes") == len(frags)
