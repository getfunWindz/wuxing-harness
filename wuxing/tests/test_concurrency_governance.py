"""TDD：限流器精确治理（壳 P1 对齐项①）——进程级共享 + 幂等配置。

背景（第七轮审查 + 壳设计 §3.6）：限流器原为模块级单例且 Engine 构造即重建——
多工作区（多 Engine 同进程）下会重置在跑额度与统计（治理近似）。
目标：Engine 构造改为「确保已配置」幂等语义（不重建、不丢统计）；
首个配置生效（进程级统一策略）；显式 configure() 保留为测试/工具后门。
"""
import pathlib
import tempfile

import pytest


@pytest.fixture(autouse=True)
def _reset_limiter():
    """测试隔离：显式重置为默认（并保证不泄漏到其他测试文件）。"""
    from wuxing.concurrency import configure
    configure(soft=64, hard=100, delay_ms=25)
    yield
    configure(soft=64, hard=100, delay_ms=25)


def _mk_engine(**kw):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    return Engine(cfg=EngineConfig(**kw),
                  workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)


def test_engine_construction_shares_limiter():
    """多 Engine 必须共享同一限流器实例（构造不重建）。"""
    from wuxing.concurrency import get_limiter
    _mk_engine()
    lim_a = get_limiter()
    _mk_engine()
    lim_b = get_limiter()
    assert lim_a is lim_b, "多 Engine 必须共享同一限流器实例（构造不得重建）"


def test_ensure_configured_preserves_stats():
    """ensure_configured 幂等：已配置 → 返回现役实例、统计不重置。"""
    from wuxing.concurrency import ensure_configured, get_limiter
    lim = get_limiter()
    lim.acquire()
    try:
        out = ensure_configured(soft=64, hard=100, delay_ms=25)
        assert out is lim, "已配置 → 必须幂等返回现役实例"
        assert get_limiter() is lim
        assert lim.stats()["active"] == 1, "统计不得重置（在跑额度保留）"
    finally:
        lim.release()


def test_engine_construction_preserves_running_stats():
    """关键场景：引擎在跑（有额度占用）时构造第二个 Engine——不得重置。"""
    from wuxing.concurrency import get_limiter
    _mk_engine()  # 首个引擎
    lim = get_limiter()
    lim.acquire()  # 模拟另一工作区在跑工具
    try:
        _mk_engine()  # 打开第二个工作区
        assert get_limiter() is lim, "Engine 构造不得替换现役限流器"
        assert lim.stats()["active"] == 1, "在跑额度不得被重置"
    finally:
        lim.release()


def test_first_wins_policy():
    """进程级统一策略：首个配置生效——后续 ensure 不覆盖（不重建）。"""
    from wuxing.concurrency import configure, ensure_configured
    configure(soft=8, hard=10, delay_ms=1)
    lim = ensure_configured(soft=64, hard=100, delay_ms=25)
    assert lim.soft == 8 and lim.hard == 10, "首配置优先（进程级统一策略）"


def test_explicit_configure_still_resets():
    """显式 configure() 语义保留：强制重建（测试/工具后门）。"""
    from wuxing.concurrency import configure, get_limiter
    lim_a = get_limiter()
    lim_b = configure(soft=32, hard=50, delay_ms=7)
    assert lim_b is not lim_a and lim_b.soft == 32, "显式 configure 必须强制重建"
