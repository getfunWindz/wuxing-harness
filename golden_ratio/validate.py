"""形状化输出结构校验器（LLM 接入降成本方案 #2：结构校验替代全量稳定性采样）。

契约：输入 LLM 返回的已解析 JSON dict（原语结构，同 MockLLM.shape_task 返回形态），
输出 (ok, normalized, errors)：
- ok：结构是否合法（字段齐全 / 节点字段合法 / id 唯一 / 边引用存在 / 无环 / 连通）；
- normalized：合法输出经清洗的深拷贝（domain_dist 归一化），非法输出为 {};
- errors：错误信息列表（逐项收集，便于 LLM 一次性纠错重试）。

与 pipeline 的关系：shape_task 解析前先过本校验器，结构合法即信任单次输出
（降成本方案 #2：无需全量 ×3 稳定性采样）；非法输出触发一次重试，再非法抛 ValueError。
"""
import copy
from types import SimpleNamespace

from golden_ratio.models import DAG

COMPLEXITIES = {"low", "mid", "high"}


def repair_dag(raw):
    """轻量修复：把「无入边且非首节点」的根挂到拓扑序前驱（仅向前补边，不引入环）。

    动机（真 LLM 实测）：模型偶发漏边产生孤立根（多根/悬空节点）——先修复再决定
    是否重试，省一次调用；修复后仍须过 validate_shape_output。
    """
    nodes = copy.deepcopy(raw["nodes"])
    edges = [list(e) for e in raw["edges"]]
    ids = [nd["id"] for nd in nodes]
    if len(set(ids)) != len(ids):
        return nodes, edges, False          # 重复 id 不可自动修复
    id_set = set(ids)
    valid = [e for e in edges if len(e) == 2 and e[0] in id_set and e[1] in id_set and e[0] != e[1]]
    valid_set = {tuple(e) for e in valid}
    indeg = {i: 0 for i in ids}
    adj = {i: [] for i in ids}
    for a, b in valid:
        adj[a].append(b)
        indeg[b] += 1
    # Kahn 拓扑序（尽力；有环时输出前缀）
    q = [i for i in ids if indeg[i] == 0]
    order, indeg2 = [], dict(indeg)
    while q:
        cur = q.pop(0)
        order.append(cur)
        for nxt in adj[cur]:
            indeg2[nxt] -= 1
            if indeg2[nxt] == 0:
                q.append(nxt)
    changed = False
    prev = None
    for nid in ids:                    # 按模型产出顺序挂接（语义自然；只向前补边 = 无环）
        if indeg[nid] == 0 and prev is not None:
            new_edge = [prev, nid]
            if tuple(new_edge) not in valid_set:
                edges.append(new_edge)
                changed = True
        prev = nid
    return nodes, edges, changed
DELIVERABLES = {"text", "code", "data", "decision"}

# S-A（2026-09-05）：deliverable 容错映射——决策链 v3.5 预见的边界落地。
# 不扩展枚举（764 基线兼容），单向最邻近映射；映射必须留痕（normalized._warns）。
DELIVERABLE_ALIASES = {"action": "text"}


def _validate_node(nd, idx, errors):
    if not isinstance(nd, dict):
        errors.append(f"nodes[{idx}] 不是对象")
        return
    if not isinstance(nd.get("id"), str) or not nd["id"].strip():
        errors.append(f"nodes[{idx}].id 缺失或非字符串")
    if not isinstance(nd.get("text"), str) or not nd["text"].strip():
        errors.append(f"nodes[{idx}].text 缺失或为空")
    dd = nd.get("domain_dist")
    if not isinstance(dd, dict) or not dd:
        errors.append(f"nodes[{idx}].domain_dist 缺失或为空")
    else:
        vals = [v for v in dd.values() if isinstance(v, (int, float)) and v > 0]
        if not vals:
            errors.append(f"nodes[{idx}].domain_dist 无正数置信度")
    if not isinstance(nd.get("trades"), list) or not nd["trades"]:
        errors.append(f"nodes[{idx}].trades 缺失或为空")
    if nd.get("complexity") not in COMPLEXITIES:
        errors.append(f"nodes[{idx}].complexity 非法: {nd.get('complexity')!r}")
    # S-A：别名（如 action→text）在 normalized 阶段容错映射——此处放行
    if (nd.get("deliverable") not in DELIVERABLES
            and nd.get("deliverable") not in DELIVERABLE_ALIASES):
        errors.append(f"nodes[{idx}].deliverable 非法: {nd.get('deliverable')!r}")
    w = nd.get("color_weight")
    if not isinstance(w, (int, float)) or not (0.0 < float(w) <= 1.0):
        errors.append(f"nodes[{idx}].color_weight 非法: {w!r}（须 (0,1]）")


def validate_shape_output(raw):
    """返回 (ok, normalized, errors)。normalized 域分布归一化并深拷贝，不修改输入。"""
    errors = []
    if not isinstance(raw, dict):
        return False, {}, ["根节点必须是 dict（已解析 JSON）"]

    nodes = raw.get("nodes")
    edges = raw.get("edges")
    total_size = raw.get("total_size")     # 伪契约（阶段0）：仅容忍存在，不强制；语义无消费方

    if not isinstance(nodes, list) or not nodes:
        errors.append("nodes 缺失或为空")
    if not isinstance(edges, list):
        errors.append("edges 缺失或非 list")
    if total_size is not None and (not isinstance(total_size, (int, float)) or total_size <= 0):
        errors.append(f"total_size 非正数: {total_size!r}")

    if errors:
        return False, {}, errors

    for idx, nd in enumerate(nodes):
        _validate_node(nd, idx, errors)

    ids = [nd.get("id") for nd in nodes if isinstance(nd, dict)]
    if len(ids) != len(set(ids)):
        errors.append("节点 id 重复")
    elif any(not isinstance(i, str) or not i.strip() for i in ids):
        pass  # id 非法的已在 _validate_node 中报告

    id_set = set(ids)
    for i, (a, b) in enumerate(edges):
        if not (isinstance(a, str) and isinstance(b, str)):
            errors.append(f"edges[{i}] 端点非字符串: {a!r} -> {b!r}")
        elif a not in id_set or b not in id_set:
            errors.append(f"edges[{i}] 引用不存在的节点: {a} -> {b}")
        elif a == b:
            errors.append(f"edges[{i}] 自环: {a} -> {a}")

    dag = DAG(nodes=[SimpleNamespace(id=nid) for nid in ids],
              edges=[(a, b) for a, b in edges
                     if isinstance(a, str) and isinstance(b, str)
                     and a in id_set and b in id_set and a != b])
    if not DAG.is_acyclic(dag):
        errors.append("依赖图存在环")

    # 连通性：所有节点必须可达（孤立节点视为解析失败，修订稿 §3.1 约束）
    if not errors:
        reachable = {nodes[0]["id"]}
        frontier = [nodes[0]["id"]]
        while frontier:
            cur = frontier.pop()
            for a, b in edges:
                if a == cur and b not in reachable:
                    reachable.add(b)
                    frontier.append(b)
                if b == cur and a not in reachable:      # 无环图反向搜索不合理，此处仅向前
                    pass
        if len(reachable) != len(ids):
            missing = sorted(set(ids) - reachable)
            errors.append(f"DAG 不连通，孤立节点: {missing}")

    if errors:
        return False, {}, errors

    # normalized：深拷贝 + domain_dist 归一化
    norm = copy.deepcopy(raw)
    warns = []
    for nd in norm["nodes"]:
        dv = nd.get("deliverable")
        if dv not in DELIVERABLES and dv in DELIVERABLE_ALIASES:
            mapped = DELIVERABLE_ALIASES[dv]
            warns.append(f"nodes[{nd.get('id')}].deliverable '{dv}' 映射为 '{mapped}'（容错）")
            nd["deliverable"] = mapped
        s = sum(v for v in nd["domain_dist"].values() if isinstance(v, (int, float)) and v > 0) or 1.0
        nd["domain_dist"] = {k: round(v / s, 4) for k, v in nd["domain_dist"].items()
                             if isinstance(v, (int, float)) and v > 0}
    if warns:
        norm["_warns"] = warns
    norm.pop("total_size", None)      # 伪契约：不进入规范化输出（算法无消费方）
    return True, norm, []
