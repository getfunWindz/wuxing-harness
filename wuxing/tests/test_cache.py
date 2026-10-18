import pathlib
import tempfile

from wuxing.cache import ReplyCache


def test_cache_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        c = ReplyCache(pathlib.Path(tmp) / "cache.json")
        c.put("k1", "hello")
        assert c.get("k1") == "hello"
        assert c.hits == 1 and c.misses == 0

def test_cache_miss():
    with tempfile.TemporaryDirectory() as tmp:
        c = ReplyCache(pathlib.Path(tmp) / "cache.json")
        assert c.get("nope") is None
        assert c.hits == 0 and c.misses == 1

def test_cache_persistence_across_instances():
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "cache.json"
        ReplyCache(p).put("k", "v")
        c2 = ReplyCache(p)
        assert c2.get("k") == "v"

def test_cache_corrupt_file_resilient():
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "cache.json"
        p.write_text("{broken", encoding="utf-8")  # 损坏
        c = ReplyCache(p)  # 不崩溃
        assert c.get("k") is None  # 静默 miss

def test_cache_deepcopy_isolates():
    with tempfile.TemporaryDirectory() as tmp:
        c = ReplyCache(pathlib.Path(tmp) / "c.json")
        c.put("k", {"items": [1]})
        v = c.get("k")
        v["items"].append(2)
        assert c.get("k")["items"] == [1]  # 深拷贝隔离

def test_cache_capacity_evicts():
    with tempfile.TemporaryDirectory() as tmp:
        c = ReplyCache(pathlib.Path(tmp) / "c.json", max_entries=2)
        c.put("a", "1"); c.put("b", "2"); c.put("c", "3")
        assert c.get("a") is None  # FIFO 逐出
        assert c.get("b") == "2"


def test_similar_get_domain_isolated():
    """缓存层加固：语义命中必须按域隔离——verify 的键不得命中 execute 的应答
    （跨域复用=污染：工具集/契约语义不同——即使 Jaccard 高也不得复用）。"""
    import pathlib
    import tempfile

    from wuxing.cache import ReplyCache

    rc = ReplyCache(pathlib.Path(tempfile.mkdtemp()) / "c.json",
                    similar_threshold=0.75)
    # execute 域键（长文本）；verify 域键共享同一任务背景（Jaccard 可高）
    rc.put("execute|任务背景：建设用户系统网站\n方案：步骤1 步骤2\n目标：完成",
           "execute-answer")
    # verify 键与 execute 键文本高度重叠（模拟跨域相似）
    val, sim = rc.similar_get("verify|任务背景：建设用户系统网站\n方案：步骤1 步骤2")
    assert val is None, \
        f"跨域语义命中必须被隔离（verify 不得复用 execute 应答——sim={sim}）"
    # 同域相似仍可命中
    rc.put("execute|任务背景：建设用户系统网站\n方案：步骤1 步骤2\n目标：完成啦",
           "execute-answer2")
    val2, _sim2 = rc.similar_get("execute|任务背景：建设用户系统网站\n方案：步骤1 步骤2\n目标：完成")
    assert val2 == "execute-answer" or val2 == "execute-answer2", \
        "同域相似命中必须保留（语义复用能力不退化）"


def _shared_lines(n: int = 150) -> str:
    """大量**互不相同** token 的共享文本（真实运行中 9.8KB 方案文档的形态）。"""
    return "\n".join(f"第{i}步：完成任务{i}并核对结果{i}与指标{i}口径。"
                      for i in range(n))


def test_similar_get_refuses_substantive_mid_difference():
    """A 级修复（精确测试 v2 暴露）：共享大前缀（多 token）+ 一行目标差异
    → Jaccard 极高，但差异段含实质指令——语义复用必须拒绝（防响应串扰）。"""
    import pathlib
    import tempfile

    from wuxing.cache import ReplyCache, _tokens_for_sim

    rc = ReplyCache(pathlib.Path(tempfile.mkdtemp()) / "c.json",
                    similar_threshold=0.75)
    shared = _shared_lines()
    k1 = f"execute|{shared}\n目标：数据模型设计：学生表与成绩表结构"
    k2 = f"execute|{shared}\n目标：交互界面实现：命令行菜单与导入导出"
    t1, t2 = _tokens_for_sim(k1), _tokens_for_sim(k2)
    sim = len(t1 & t2) / len(t1 | t2)
    assert sim >= 0.75, f"构造前提：Jaccard 必须达阈值（实际 {sim:.3f}）"
    rc.put(k1, "OUT-DATA")
    val, _ = rc.similar_get(k2)
    assert val is None, "实质差异不得语义复用（跨单元响应串扰）"


def test_similar_get_allows_punctuation_and_tiny_drift():
    """标点/空白微漂移与极短漂移（≤四字符）仍可复用（原能力不退）。"""
    import pathlib
    import tempfile

    from wuxing.cache import ReplyCache

    rc = ReplyCache(pathlib.Path(tempfile.mkdtemp()) / "c.json",
                    similar_threshold=0.75)
    shared = _shared_lines()
    rc.put(f"execute|{shared}\n目标：写一个班级成绩系统的报告。", "OUT")
    val, _ = rc.similar_get(f"execute|{shared}\n目标：写一个班级成绩系统的报告！")
    assert val == "OUT", "标点漂移必须命中"
