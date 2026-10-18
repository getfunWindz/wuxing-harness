"""契约层测试（阶段 0：契约开放化）。

决策（算法结构评估报告 §四-阶段 0）：
1. LLM 输出契约为唯一契约源：{id,text,domain_dist,trades,complexity,deliverable,color_weight}；
   样例/dag_spec 格式（domain/weight）仅历史兼容（转换函数隔离）；
2. total_size 为伪契约（LLM 误解为节点数、算法无消费方）→ 移出契约、校验宽松化（可选字段）；
3. 领域/工种为开放标签（不映射闭合）。
"""
from golden_ratio.contract import LLM_NODE_FIELDS, llm_to_spec, spec_to_llm
from golden_ratio.validate import validate_shape_output


def _llm_node(nid="n1", field="n1"):
    return {"id": nid, "text": "节点", "domain_dist": {"软件工程": 0.8, "设备": 0.2},
            "trades": ["数据工程师", "产品经理"], "complexity": "mid",
            "deliverable": "code", "color_weight": 0.7}


def test_contract_fields_are_llm_shape():
    """契约字段 = LLM 输出字段（无 total_size——伪契约已移除）。"""
    assert "id" in LLM_NODE_FIELDS and "domain_dist" in LLM_NODE_FIELDS
    assert "color_weight" in LLM_NODE_FIELDS
    assert "total_size" not in LLM_NODE_FIELDS, "total_size 已移出契约"


def test_llm_to_spec_maps_fields():
    spec = llm_to_spec([_llm_node()])
    n = spec[0]
    assert n["domain"] == {"软件工程": 0.8, "设备": 0.2}   # domain_dist → domain
    assert n["weight"] == 0.7                          # color_weight → weight
    assert "domain_dist" not in n, "转换后不残留新格式字段"


def test_spec_to_llm_roundtrip():
    """双向转换恒等（历史数据迁移到契约格式）。"""
    spec = llm_to_spec([_llm_node()])
    lln = spec_to_llm(spec)[0]
    assert lln["domain_dist"] == {"软件工程": 0.8, "设备": 0.2}
    assert lln["color_weight"] == 0.7
    assert lln["trades"] == ["数据工程师", "产品经理"]


def test_validate_accepts_missing_total_size():
    """total_size 可选：无该字段仍合法（伪契约移除后校验宽松化）。"""
    raw = {"nodes": [_llm_node()], "edges": []}
    ok, norm, errs = validate_shape_output(raw)
    assert ok, errs
    assert "total_size" not in norm


def test_validate_ignores_bogus_total_size():
    """total_size 若仍存在（旧模板兼容）：不阻止合法输出，也不进入 normalized。"""
    raw = {"nodes": [_llm_node()], "edges": [], "total_size": 5}
    ok, norm, errs = validate_shape_output(raw)
    assert ok, errs
    assert "total_size" not in norm, "伪字段不进入规范化输出"


def test_prompt_no_longer_asks_total_size():
    """系统提示不再要求 total_size（防契约回退）。"""
    from golden_ratio.realllm import SHAPE_SYSTEM_PROMPT
    assert "total_size" not in SHAPE_SYSTEM_PROMPT
