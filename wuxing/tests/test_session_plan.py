"""G8-M2：会话计划类型助手（session_plan）——设计轮/执行与引擎闸单一来源。"""
from wuxing.session_plan import session_plan


def _theroad(tmp_path, session="conversation-w.jsonl"):
    from wuxing.session_modes import save
    save(tmp_path, session, "theroad", "")
    return session


def test_non_theroad_session_is_execution(tmp_path):
    assert session_plan(tmp_path, "conversation-a.jsonl")["kind"] == "execution"


def test_theroad_without_map_is_design(tmp_path):
    s = _theroad(tmp_path)
    assert session_plan(tmp_path, s)["kind"] == "design"


def test_theroad_map_but_no_spec_is_design(tmp_path):
    s = _theroad(tmp_path)
    from wuxing.map_doc import write_sections
    write_sections(tmp_path, destination="目标", route="- [ ] 实现")
    assert session_plan(tmp_path, s)["kind"] == "design"


def test_theroad_map_spec_no_ready_tickets_is_design_then_execution(tmp_path):
    s = _theroad(tmp_path)
    from wuxing import design_state, spec_doc, tickets
    from wuxing.map_doc import write_sections
    write_sections(tmp_path, destination="目标", route="- [ ] 实现")
    e = spec_doc.write(tmp_path, title="规格", sections={"problem": "p"})
    design_state.save(tmp_path, {"spec_slug": e["slug"], "spec_path": e["path"]})
    tickets.create(tmp_path, title="切片")
    assert session_plan(tmp_path, s)["kind"] == "design"
    tickets.publish(tmp_path)
    assert session_plan(tmp_path, s)["kind"] == "execution"


def test_phase_ready_is_execution(tmp_path):
    s = _theroad(tmp_path)
    from wuxing import design_state
    design_state.save(tmp_path, {"phase": "ready"})
    assert session_plan(tmp_path, s)["kind"] == "execution"


def test_default_mode_from_effective_config(tmp_path, monkeypatch):
    import wuxing.config_contract as cc
    monkeypatch.setattr(
        cc, "effective_config",
        lambda workdir=None: {"values": {"mode_default": "theroad"},
                              "sources": {}})
    assert session_plan(tmp_path, "conversation-x.jsonl")["kind"] == "design"
