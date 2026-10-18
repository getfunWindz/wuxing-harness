"""E3-5/CU10：运行时产物清理纪律（双上限 / 最旧先删 / 失败跳过 / debounce）。

计划：docs/plans/2026-10-04-wuxing-cleanup-discipline.md（T1-T3）。
纪律：只清 `.wuxing/` 内部（sessions/reports）与显式目录；绝不触碰用户交付物。
"""
import importlib.util
import os
import pathlib
import time

from wuxing.cleanup import maybe_cleanup, prune_dir, prune_dirs
from wuxing.config import EngineConfig


def _mk(d: pathlib.Path, name: str, size: int, age_s: float = 0):
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(b"x" * size)
    if age_s:
        t = time.time() - age_s
        os.utime(p, (t, t))
    return p


# ---------------- T1：prune_dir（双上限/最旧先删） ----------------

def test_prune_by_files_oldest_first(tmp_path):
    for i in range(5):
        _mk(tmp_path, f"{i:03d}.jsonl", 10, age_s=100 - i)
    out = prune_dir(tmp_path, "*.jsonl", max_files=2, max_bytes=10**9)
    left = sorted(p.name for p in tmp_path.glob("*.jsonl"))
    assert left == ["003.jsonl", "004.jsonl"]      # 最旧 000/001/002 删除
    assert out["removed"] == 3


def test_prune_by_bytes(tmp_path):
    _mk(tmp_path, "a.jsonl", 100, age_s=30)
    _mk(tmp_path, "b.jsonl", 100, age_s=20)
    _mk(tmp_path, "c.jsonl", 100, age_s=10)
    out = prune_dir(tmp_path, "*.jsonl", max_files=100, max_bytes=150)
    left = sorted(p.name for p in tmp_path.glob("*.jsonl"))
    assert left == ["c.jsonl"]                     # 只留最新，直到满足字节上限
    assert out["freed"] >= 200


def test_prune_missing_dir_noop(tmp_path):
    assert prune_dir(tmp_path / "nope", "*.jsonl", 1, 1)["removed"] == 0


def test_prune_failure_skipped(tmp_path, monkeypatch):
    """删不掉跳过（不虚减计数/不绕失败）。"""
    _mk(tmp_path, "old.jsonl", 10, age_s=100)
    _mk(tmp_path, "new.jsonl", 10, age_s=1)
    real_unlink = pathlib.Path.unlink

    def flaky_unlink(self, *a, **k):
        if self.name == "old.jsonl":
            raise PermissionError("locked")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "unlink", flaky_unlink)
    out = prune_dir(tmp_path, "*.jsonl", max_files=1, max_bytes=10**9)
    assert (tmp_path / "old.jsonl").exists(), "失败项必须保留（下次再试）"
    assert (tmp_path / "new.jsonl").exists()
    assert out["removed"] == 0


# ---------------- T2：配置与 debounce ----------------

def test_cleanup_config_defaults():
    cfg = EngineConfig()
    assert cfg.cleanup_enabled is True
    assert cfg.cleanup_interval_s == 3600
    assert cfg.cleanup_sessions_max == 300
    assert cfg.cleanup_reports_max == 300


def test_maybe_cleanup_debounce(tmp_path):
    cfg = EngineConfig(cleanup_sessions_max=1)
    sess = tmp_path / ".wuxing" / "sessions"
    _mk(sess, "1.jsonl", 10, age_s=100)
    _mk(sess, "2.jsonl", 10, age_s=50)
    _mk(sess, "3.jsonl", 10, age_s=1)
    t0 = time.time()
    out1 = maybe_cleanup(tmp_path, cfg, now=t0)
    assert out1["ran"] is True and out1["removed"] >= 2
    assert len(list(sess.glob("*.jsonl"))) == 1
    # debounce：间隔内二次调用跳过（新增文件也不清）
    _mk(sess, "4.jsonl", 10, age_s=0)
    out2 = maybe_cleanup(tmp_path, cfg, now=t0 + 10)
    assert out2["ran"] is False
    assert len(list(sess.glob("*.jsonl"))) == 2
    # 超时后再次执行
    _mk(sess, "5.jsonl", 10, age_s=0)
    out3 = maybe_cleanup(tmp_path, cfg, now=t0 + cfg.cleanup_interval_s + 1)
    assert out3["ran"] is True
    assert len(list(sess.glob("*.jsonl"))) == 1


def test_maybe_cleanup_disabled_and_trace(tmp_path):
    out = maybe_cleanup(tmp_path, EngineConfig(cleanup_enabled=False), now=0)
    assert out["ran"] is False and out["removed"] == 0
    # trace 事件（清理可审计）
    from wuxing.trace import TraceLogger
    cfg = EngineConfig(cleanup_sessions_max=1)
    sess = tmp_path / ".wuxing" / "sessions"
    _mk(sess, "a.jsonl", 10, age_s=100)
    _mk(sess, "b.jsonl", 10, age_s=1)
    trace = TraceLogger(tmp_path / ".wuxing" / "trace.jsonl")
    out2 = maybe_cleanup(tmp_path, cfg, trace=trace, now=0)
    assert out2["ran"] is True and out2["removed"] == 1
    events = [r for r in trace.load() if r.get("event") == "cleanup"]
    assert events and "removed" in events[0] and "freed" in events[0]


# ---------------- T3：批次目录保留（E2E 产物） ----------------

def test_prune_dirs_keep_latest(tmp_path):
    art = tmp_path / "artifacts"
    for i in range(4):
        d = art / f"{i:02d}"
        d.mkdir(parents=True)
        (d / "x.log").write_text("x")
        t = time.time() - (100 - i)
        os.utime(d, (t, t))
    out = prune_dirs(art, "*", keep=2)
    left = sorted(p.name for p in art.iterdir())
    assert left == ["02", "03"]
    assert out["removed"] == 2


def _load_run_all():
    root = pathlib.Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "e2e_run_all", root / "e2e" / "shell" / "run_all.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_e2e_retention_helper(tmp_path):
    """run_all 收尾保留最近 K 批（纯函数 helper）。"""
    mod = _load_run_all()
    art = tmp_path / "artifacts"
    for i in range(25):
        d = art / f"{i:02d}"
        d.mkdir(parents=True)
        (d / "x.log").write_text("x")
        t = time.time() - (100 - i)
        os.utime(d, (t, t))
    removed = mod.prune_batches(art, keep=20)
    left = sorted(p.name for p in art.iterdir())
    assert removed == 5
    assert len(left) == 20 and "24" in left and "00" not in left
