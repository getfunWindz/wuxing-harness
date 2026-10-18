import pathlib

from wuxing.engine import Engine
from wuxing.prompt_builder import build_prompt, build_system_text


def test_plan_system_prefix_is_task_independent(tmp_path):
    """B1（v65）：plan system 段不随任务/工作区变化（跨任务前缀稳定的前提）。"""
    eng_a = Engine(workdir=pathlib.Path(tmp_path) / "a", auto_confirm=True)
    eng_b = Engine(workdir=pathlib.Path(tmp_path) / "b", auto_confirm=True)
    domain_a = eng_a.registry.get("plan")
    domain_b = eng_b.registry.get("plan")
    tools_a = eng_a.tools.filter(domain_a.tool_whitelist, domain_id="plan")
    tools_b = eng_b.tools.filter(domain_b.tool_whitelist, domain_id="plan")
    text_a = build_system_text(domain_a, tools_a, True, eng_a.cfg.max_unit_budget)
    text_b = build_system_text(domain_b, tools_b, True, eng_b.cfg.max_unit_budget)
    assert text_a == text_b


def test_plan_user_prompt_keeps_shared_task_background_prefix(tmp_path):
    """B1（v65）：plan 首条 user 消息以任务背景开头（goal 差异在尾部）。"""
    eng = Engine(workdir=pathlib.Path(tmp_path) / "ws", auto_confirm=True)
    domain = eng.registry.get("plan")
    p1 = build_prompt(domain, {"goal": "目标甲"}, "同一个任务背景", [])
    p2 = build_prompt(domain, {"goal": "目标乙"}, "同一个任务背景", [])
    prefix = "任务背景：同一个任务背景\n请为任务制定方案："
    assert p1.startswith(prefix)
    assert p2.startswith(prefix)
