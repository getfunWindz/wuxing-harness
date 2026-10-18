"""TDD · M3-4：C 项清理——C1 provenance 锁生效/C2 原子写/C5 英文词边界。"""
import pathlib
import tempfile
import threading

from wuxing.provenance import ProvenanceLedger
from wuxing.state import TaskState, load_state, save_state


def test_c1_provenance_lock_used():
    """C1：并发 record 不丢行/不损坏（锁真正生效——前实现锁死）。"""
    p = pathlib.Path(tempfile.mkdtemp()) / "p.jsonl"
    ledger = ProvenanceLedger(p)
    errors = []

    def worker(i):
        try:
            for j in range(20):
                ledger.record(unit_id=f"u-{i}-{j}", domain="d")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"并发写入异常：{errors[:2]}"
    assert len(ledger.load()) == 80, f"行数丢失：{len(ledger.load())}（锁未生效）"


def test_c2_state_atomic_write():
    """C2：task_state 原子写（tmp+rename——崩溃不产生半写损坏）。"""
    d = pathlib.Path(tempfile.mkdtemp())
    sp = d / "task_state.json"
    save_state(TaskState(task_text="t", fragments=[], units=[], status="done"), sp)
    state = load_state(sp)
    assert state.task_text == "t" and state.status == "done"
    # 原子写实现检查：临时文件不存在残留
    assert not list(d.glob("*.tmp*")), "原子写应清理临时文件"


def test_c5_english_word_boundary():
    """C5：英文关键词词边界（'test' 不得命中 'latest'/'contest'——子串误路由）。"""
    from wuxing.router import route_fragment
    assert route_fragment("latest version") == "execute", \
        f"'latest' 含 'test' 子串——必须词边界匹配：{route_fragment('latest version')}"
    assert route_fragment("test the login page") == "verify", \
        "'test' 独立词应路由 verify"
    assert route_fragment("add login feature") == "execute", \
        "'add' 词边界（不吞 'adding' 前缀场景）"
