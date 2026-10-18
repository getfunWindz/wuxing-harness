def test_user_conditional_domain():
    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry
    reg = DomainRegistry(EngineConfig())
    # user 低频（320 套件 2.5%）→ 条件域
    assert reg.is_conditional("user") is True
    # verify 高覆盖（60.6%）→ 保留为常驻域
    assert reg.is_conditional("verify") is False
    assert reg.is_conditional("execute") is False
    assert reg.is_conditional("plan") is False

def test_engine_no_verify_fallback_chain():
    import pathlib
    import tempfile

    from wuxing.engine import Engine
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    frags = eng._build_fragments("写一篇请假邮件")  # 无 verify 语义
    # 不再有 F-verify0 机械补链
    assert not any(f["fragment_id"] == "F-verify0" for f in frags)
    # plan 补链仍保留（规划总是需要）
    assert any(f["domain"] == "plan" for f in frags)

def test_router_vocab_expanded():
    from wuxing.router import route_fragment
    # 高频节点词（320 套件节点文本反馈）
    assert route_fragment("撰写报告草稿") == "execute"
    assert route_fragment("整理会议纪要") == "execute"
    assert route_fragment("收集用户反馈") == "execute"
    assert route_fragment("审查代码变更") == "verify"
    assert route_fragment("分析性能瓶颈") == "execute"
