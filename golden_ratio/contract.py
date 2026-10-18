"""契约层（阶段 0：契约开放化——LLM 输出契约为唯一契约源）。

策略（算法结构评估报告 §四-阶段 0 决策）：
- 领域/工种为**开放标签**（任意字符串 + 置信度分布），不做闭合映射（映射表被 774 唯一标签否决）；
- 契约字段（LLM 输出）：id/text/domain_dist/trades/complexity/deliverable/color_weight；
  **total_size 已移出契约**（LLM 误解为节点数、算法无消费方——伪契约）；
- 历史/数据文件格式（domain/weight）仅兼容层：llm_to_spec / spec_to_llm 双向转换，
  新数据一律契约格式。

统一契约（LLMClient 文档 + 本模块为唯一权威）：
    Node ::= {id: str, text: str, domain_dist: {开放领域: float>0},
              trades: [开放工种...], complexity: "low"|"mid"|"high",
              deliverable: "text"|"code"|"data"|"decision", color_weight: (0,1]}
    DAG  ::= {nodes: [Node...], edges: [[上游id, 下游id]...]}
"""

LLM_NODE_FIELDS = ("id", "text", "domain_dist", "trades", "complexity",
                   "deliverable", "color_weight")
SPEC_NODE_FIELDS = ("id", "text", "domain", "trades", "complexity",
                    "deliverable", "weight")


def llm_to_spec(nodes):
    """契约格式 → 历史 dag_spec 格式（domain_dist→domain, color_weight→weight）。

    仅用于兼容读入现存数据文件；新数据应保持契约格式。
    """
    out = []
    for nd in nodes:
        out.append({"id": nd["id"], "text": nd["text"],
                    "domain": dict(nd["domain_dist"]),
                    "trades": list(nd["trades"]),
                    "complexity": nd["complexity"],
                    "deliverable": nd["deliverable"],
                    "weight": float(nd["color_weight"])})
    return out


def spec_to_llm(nodes):
    """历史 dag_spec 格式 → 契约格式（含校验缺失字段则 KeyError 前浮层：信任输入）。"""
    out = []
    for nd in nodes:
        out.append({"id": nd["id"], "text": nd["text"],
                    "domain_dist": dict(nd["domain"]),
                    "trades": list(nd["trades"]),
                    "complexity": nd["complexity"],
                    "deliverable": nd["deliverable"],
                    "color_weight": float(nd["weight"])})
    return out
