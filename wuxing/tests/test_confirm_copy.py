"""确认门文案模块单测（重大优化清单 #2 · A′）：四要素/触发/位置/浏览器/禁词 lint。"""
import pytest

from wuxing import confirm_copy


def test_unit_confirm_view_four_elements_all_triggers():
    for trigger in ("domain_policy", "threshold", "session_switch", "recovered"):
        v = confirm_copy.unit_confirm_view(
            impact={"summary": "生成统计脚本", "tools": ["bash"],
                    "depends": ["U-0"], "deliverables": ["统计脚本"]},
            trigger=trigger, index=2, total=5)
        for key in ("title", "object", "allow_effect", "deny_effect",
                    "action_hint", "trigger", "position"):
            assert str(v.get(key, "")).strip(), f"{trigger} 缺字段 {key}"
        assert "第 2 步" in v["position"] and "共 5 步" in v["position"]
        assert v["details"]["tools"] == ["bash"]
        assert v["options"] == ["批准", "驳回"]


def test_unit_confirm_view_summary_fallback_and_no_position():
    v = confirm_copy.unit_confirm_view(impact=None)
    assert v["object"].strip()
    assert v["position"] == ""
    assert v["details"] == {"tools": [], "depends": [], "deliverables": [],
                            "summary": ""}


def test_unit_confirm_view_unknown_trigger_is_loud():
    with pytest.raises(KeyError):
        confirm_copy.unit_confirm_view(trigger="no-such-trigger")


def test_browser_access_view_loopback_and_lan():
    v = confirm_copy.browser_access_view(
        address="127.0.0.1:3000", occupant_label="node.exe",
        agent_reason="核查登录页")
    assert "127.0.0.1:3000" in v["title"] and "node.exe" in v["title"]
    assert "允许后" in v["title"] and "拒绝后" in v["title"]
    assert "未核实" in v["title"] and len(v["title"]) <= 200
    assert v["options"] == ["允许访问", "拒绝"]
    lan = confirm_copy.browser_access_view(address="192.168.1.10:80",
                                           source="lan")
    assert "局域网" in lan["title"] and "无鉴权" in lan["title"]
    assert lan["title"].count("内网") <= 1, "LAN 文案不得重复赘词"


def test_templates_no_banned_terms():
    joined = "".join(s for group in confirm_copy.TEMPLATES.values()
                     for s in group.values())
    for compound in confirm_copy.ALLOWED_COMPOUNDS:   # 人话复合词豁免（如「局域网」）
        joined = joined.replace(compound, "")
    hits = [t for t in confirm_copy.BANNED_TERMS if t in joined]
    assert hits == [], f"固定文案含禁词：{hits}"
