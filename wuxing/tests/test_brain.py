import pathlib
import tempfile

from wuxing.llm.brain import BrainMemory


def test_record_and_search():
    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "brain.json")
    mem.record(key="登录|验证", domain="verify", model="claude", success=True)
    hits = mem.search("登录 验证 修复")
    assert len(hits) >= 1
    assert hits[0]["model"] == "claude"
    assert hits[0]["similarity"] > 0.5

def test_persistence_roundtrip():
    p = pathlib.Path(tempfile.mkdtemp()) / "brain.json"
    mem = BrainMemory(p)
    mem.record(key="a|b", domain="plan", model="ds", success=True)
    mem2 = BrainMemory(p)
    assert len(mem2.cases) == 1

def test_success_rate_and_attempts():
    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")
    mem.record(key="k", domain="d", model="m", success=True)
    mem.record(key="k", domain="d", model="m", success=False)
    c = mem.cases[0]
    assert c["attempts"] == 2
    assert c["success"] is False  # 最近一次（案例式非累计）

def test_lru_eviction():
    p = pathlib.Path(tempfile.mkdtemp()) / "b.json"
    mem = BrainMemory(p, max_cases=2)
    mem.record(key="a", domain="d", model="m", success=True)
    mem.record(key="b", domain="d", model="m", success=True)
    mem.record(key="c", domain="d", model="m", success=True)
    assert len(mem.cases) == 2  # LRU 淘汰

def test_search_empty_returns_empty():
    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")
    assert mem.search("任意") == []


def test_concurrent_record_merges():
    """B3：并发 record 同 key+domain+model 必须合并为一条（attempts 精确累加）——无锁竞态丢合并。"""
    import sys
    import threading
    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")
    barrier = threading.Barrier(16)
    # B3 测试：强制字节码级交错（默认 5ms 切换间隔下窗口难现）
    _old_iv = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)

    def worker():
        barrier.wait()  # 同刻冲刺——放大 check-then-act 交错窗口
        for _ in range(50):
            mem.record(key="ck", domain="d", model="m", success=True)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    sys.setswitchinterval(_old_iv)
    assert len(mem.cases) == 1, f"同 key 必须合并为 1 条（实际 {len(mem.cases)}）"
    assert mem.cases[0]["attempts"] == 800, \
        f"attempts 必须精确累加（实际 {mem.cases[0]['attempts']}）"


def test_record_tracks_success_count():
    """B1：record 必须维护 success_count（成功率分母精确）——仅靠 latest 布尔无法算成功率。"""
    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")
    for ok in (True, True, False, True):
        mem.record(key="sk", domain="d", model="m", success=ok)
    c = mem.cases[0]
    assert c["attempts"] == 4
    assert c["success_count"] == 3, f"精确成功计数（实际 {c.get('success_count')}）"
    assert c["success"] is True  # 最新一次


def test_case_success_rate():
    """B1：成功率口径 = success_count/attempts（规格「成功率≥0.8」的实现基础）。"""
    from wuxing.llm.brain import case_success_rate
    assert case_success_rate({"attempts": 5, "success_count": 4}) == 0.8
    assert case_success_rate({"attempts": 3, "success_count": 2}) < 0.8
    assert case_success_rate({"attempts": 1, "success_count": 1}) == 1.0
    assert case_success_rate({"attempts": 0, "success_count": 0}) == 0.0
    # 旧数据兼容：无 success_count → 回退 latest 布尔（1 样本估计）
    assert case_success_rate({"attempts": 3, "success": True}) == 1.0
    assert case_success_rate({"attempts": 3, "success": False}) == 0.0


def test_strong_evidence_uses_rate_not_latest():
    """B1：强证据判定必须用成功率（规格≥0.8）——「最新成功但历史 2/3」不构成强证据。"""
    from wuxing.llm.router import strong_evidence
    # 最新成功但成功率 0.667 < 0.8 → 非强证据（现状：latest=True 会被误判强）
    assert not strong_evidence({
        "similarity": 0.9, "attempts": 3, "success_count": 2,
        "success": True})
    # 成功率 0.8 且相似高 → 强证据
    assert strong_evidence({
        "similarity": 0.9, "attempts": 5, "success_count": 4,
        "success": False})
    # 相似不足 → 非强
    assert not strong_evidence({
        "similarity": 0.5, "attempts": 5, "success_count": 5,
        "success": True})


def test_save_atomic_keeps_old_file_on_replace_failure(tmp_path, monkeypatch):
    """B3（技术债收口 2026-09-12）：brain._save 原子写——替换阶段失败旧文件完好。"""
    import wuxing.llm.brain as bmod
    p = tmp_path / "brain.json"
    mem = bmod.BrainMemory(p)
    mem.record(key="k1", domain="d", model="m", success=True)
    old = p.read_text(encoding="utf-8")

    def _boom(*_a, **_k):
        raise OSError("boom")

    monkeypatch.setattr(bmod.os, "replace", _boom)
    mem.record(key="k2", domain="d", model="m", success=True)
    assert p.read_text(encoding="utf-8") == old, \
        "替换失败→旧文件必须完好（原子写；不得半写破坏）"
