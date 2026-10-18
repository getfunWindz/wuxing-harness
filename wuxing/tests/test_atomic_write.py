"""原子写助手：重试与失败语义（Windows 瞬态占用回归守卫）。"""
import os

import pytest

from wuxing.atomic_write import atomic_write_text


def test_writes_and_replaces(tmp_path):
    target = tmp_path / "a.jsonc"
    atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    assert not list(tmp_path.glob("*.tmp"))


def test_retries_transient_replace_failure(tmp_path, monkeypatch):
    target = tmp_path / "b.jsonc"
    calls = {"n": 0}
    real_replace = os.replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(5, "拒绝访问")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    atomic_write_text(target, "ok")
    assert calls["n"] == 3
    assert target.read_text(encoding="utf-8") == "ok"


def test_raises_after_exhausted(tmp_path, monkeypatch):
    target = tmp_path / "c.jsonc"

    def always_fail(src, dst):
        raise PermissionError(5, "拒绝访问")

    monkeypatch.setattr(os, "replace", always_fail)
    with pytest.raises(PermissionError):
        atomic_write_text(target, "x")
