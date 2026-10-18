import pathlib
import tempfile

from wuxing.engine import Engine


def test_engine_activates_user_when_semantic_hit():
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    eng.run_task("定义用户视角的验收标准与体验要求")  # 含 user 专用短语
    assert "user" in eng.registry.active_ids()

def test_engine_user_not_active_for_normal_task():
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    eng.run_task("编写用户系统的后端代码")  # '用户系统'非专用短语
    assert "user" not in eng.registry.active_ids()

def test_router_conditional_fallback():
    from wuxing.router import route_fragment
    # 条件域未启用时：user 命中 → 回退 execute
    assert route_fragment("从用户视角优化界面", active={"plan", "execute", "verify"}) == "execute"
    # 启用时：正常 user
    assert route_fragment("从用户视角优化界面", active={"plan", "execute", "verify", "user"}) == "user"

def test_engine_pending_when_confirm_required():
    """边界修复回归：挂起单位存在 → 状态 pending（非 done）。"""
    import pathlib
    import tempfile

    from wuxing.config import EngineConfig
    eng = Engine(cfg=EngineConfig(confirm_threshold=1.0),
                 workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=False)
    r = eng.run_task("写一篇请假邮件")
    assert r.status == "pending"
    assert any(u.status == "needs_confirm" for u in r.units)
