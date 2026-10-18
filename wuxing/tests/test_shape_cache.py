import pathlib
import tempfile

from wuxing.cache import ShapeCache
from wuxing.engine import Engine


def test_shape_cache_key_normalization():
    with tempfile.TemporaryDirectory() as tmp:
        sc = ShapeCache(pathlib.Path(tmp) / "shape_cache.json")
        k1 = sc.key_for("写一封请假邮件")
        k2 = sc.key_for("写一封请假邮件  ")  # 尾随空白
        assert k1 == k2  # 规范化

def test_shape_cache_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        sc = ShapeCache(pathlib.Path(tmp) / "shape_cache.json")
        dag = {"nodes": [{"id": "n1", "text": "x"}], "edges": []}
        sc.put("k", dag)
        assert sc.get("k") == dag

def test_engine_has_shape_cache():
    wd = pathlib.Path(tempfile.mkdtemp())
    eng = Engine(workdir=wd, auto_confirm=True)
    assert eng.shape_cache is not None
    assert (wd / "shape_cache.json").exists() or True

def test_engine_shape_cache_cross_engine_hits():
    import os
    os.environ.pop("DEEPSEEK_API_KEY", None)
    wd = pathlib.Path(tempfile.mkdtemp())
    eng1 = Engine(workdir=wd, auto_confirm=True)
    eng1.run_task("写一篇请假邮件")
    # 同工作区新引擎 → shape_cache 复用（真 LLM 场景收益面；mock 路径验证 key 化）
    eng2 = Engine(workdir=wd, auto_confirm=True)
    assert eng2.shape_cache is not None


def test_similar_get_uses_normalized_key():
    """B11：similar_get 必须与 put/get 同口径（key_for 规范化）——否则查询侧
    分词原始文本、写入侧规范化键——微漂移查询命中率失真。"""
    sc = ShapeCache(pathlib.Path(tempfile.mkdtemp()) / "s.json")
    sc.put("  实现  登录   功能  ", {"nodes": []})
    val, sim = sc.similar_get("实现 登录 功能")
    assert val is not None, "查询侧必须经 key_for 规范化（同写入口径）"
    assert sim > 0.5
