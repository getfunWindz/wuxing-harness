"""形状化输出结构校验器测试（LLM接入降成本方案 #2：结构校验替代全量稳定性采样）。

校验器的契约：仅接受 dict/list 原语（模拟 LLM 返回的已解析 JSON），
输出 (ok, normalized, errors)——normalized 是对合法输出的规范化副本。
"""
from golden_ratio.validate import validate_shape_output


def _valid_email_like():
    return {
        "nodes": [
            {"id": "n1", "text": "撰写请假邮件", "domain_dist": {"写作": 0.9},
             "trades": ["创作"], "complexity": "low",
             "deliverable": "text", "color_weight": 0.5},
        ],
        "edges": [],
        "total_size": 1.0,
    }


def test_validate_accepts_minimal_valid_output():
    ok, norm, errs = validate_shape_output(_valid_email_like())
    assert ok is True
    assert errs == []
    assert len(norm["nodes"]) == 1


def test_validate_rejects_missing_fields():
    raw = {"nodes": []}                      # 缺 edges/total_size
    ok, _, errs = validate_shape_output(raw)
    assert ok is False
    assert any("edges" in e or "total_size" in e for e in errs)


def test_validate_rejects_empty_nodes():
    ok, _, errs = validate_shape_output({"nodes": [], "edges": [], "total_size": 1.0})
    assert ok is False
    assert any("nodes" in e for e in errs)


def test_validate_rejects_duplicate_node_ids():
    raw = _valid_email_like()
    raw["nodes"].append(dict(raw["nodes"][0]))     # id 重复
    ok, _, errs = validate_shape_output(raw)
    assert ok is False
    assert any("重复" in e or "duplicate" in e.lower() for e in errs)


def test_validate_rejects_edge_to_unknown_node():
    raw = _valid_email_like()
    raw["edges"] = [["n1", "ghost"]]
    ok, _, errs = validate_shape_output(raw)
    assert ok is False
    assert any("ghost" in e for e in errs)


def test_validate_rejects_cycle():
    raw = _valid_email_like()
    raw["nodes"].append({"id": "n2", "text": "b", "domain_dist": {"写作": 1.0},
                         "trades": ["创作"], "complexity": "low",
                         "deliverable": "text", "color_weight": 0.5})
    raw["edges"] = [["n1", "n2"], ["n2", "n1"]]
    ok, _, errs = validate_shape_output(raw)
    assert ok is False
    assert any("环" in e or "cycle" in e.lower() for e in errs)


def test_validate_rejects_disconnected_dag():
    raw = _valid_email_like()
    raw["nodes"].append({"id": "n2", "text": "b", "domain_dist": {"写作": 1.0},
                         "trades": ["创作"], "complexity": "low",
                         "deliverable": "text", "color_weight": 0.5})
    raw["edges"] = []                            # n2 孤立
    ok, _, errs = validate_shape_output(raw)
    assert ok is False
    assert any("连通" in e or "connect" in e.lower() for e in errs)


def test_validate_normalizes_domain_dist():
    raw = _valid_email_like()
    raw["nodes"][0]["domain_dist"] = {"写作": 0.9, "分析": 0.3}   # 未归一
    ok, norm, _ = validate_shape_output(raw)
    assert ok is True
    d = norm["nodes"][0]["domain_dist"]
    assert abs(sum(d.values()) - 1.0) < 1e-6


def test_validate_rejects_bad_color_weight():
    raw = _valid_email_like()
    raw["nodes"][0]["color_weight"] = 1.5          # 超出 (0,1]
    ok, _, errs = validate_shape_output(raw)
    assert ok is False
    assert any("color_weight" in e for e in errs)


def test_validate_rejects_bad_complexity_or_deliverable():
    raw = _valid_email_like()
    raw["nodes"][0]["complexity"] = "huge"
    ok, _, errs = validate_shape_output(raw)
    assert ok is False
    assert any("complexity" in e for e in errs)
    raw = _valid_email_like()
    raw["nodes"][0]["deliverable"] = "song"
    ok, _, errs = validate_shape_output(raw)
    assert ok is False
    assert any("deliverable" in e for e in errs)


def test_validate_does_not_mutate_input():
    raw = _valid_email_like()
    import copy
    snapshot = copy.deepcopy(raw)
    validate_shape_output(raw)
    assert raw == snapshot


# ── S-A：deliverable 容错映射（决策链 v3.5 预见的边界落地——2026-09-05）── #

def test_validate_maps_action_to_text():
    """行动型交付（'action'）→ 容错映射为 text（文档类交付物最邻近）。

    冒烟实证：真 LLM 对"写一封请假邮件"输出 deliverable='action' → 校验拒绝 →
    形状化失败。v3.5 报告已预见「交付物体系可能不足（审批链类边界）」——
    落地为单向最邻近映射（不扩展枚举——764 基线兼容）。
    """
    raw = _valid_email_like()
    raw["nodes"][0]["deliverable"] = "action"
    ok, norm, errs = validate_shape_output(raw)
    assert ok is True, f"action 应被映射接受（不重试）：{errs}"
    assert norm["nodes"][0]["deliverable"] == "text"
    warns = norm.get("_warns", [])
    assert any("action" in w and "text" in w for w in warns), \
        f"映射必须留痕（可审计）：{warns}"


def test_validate_still_rejects_unknown_deliverable():
    """非常规非法值（如 'song'）仍拒绝（映射表之外不猜测）。"""
    raw = _valid_email_like()
    raw["nodes"][0]["deliverable"] = "song"
    ok, _, errs = validate_shape_output(raw)
    assert ok is False
    assert any("deliverable" in e for e in errs)


def test_validate_mapping_does_not_mutate_input():
    """映射发生在 normalized（深拷贝）——原输入不被修改。"""
    raw = _valid_email_like()
    raw["nodes"][0]["deliverable"] = "action"
    import copy
    snapshot = copy.deepcopy(raw)
    validate_shape_output(raw)
    assert raw == snapshot
    assert raw["nodes"][0]["deliverable"] == "action"
