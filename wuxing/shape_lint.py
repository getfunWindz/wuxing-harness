"""拆分 lint（P1-2 · 用户裁决 2026-09-27）：形状化结果的机械校验与防御性处置。

规则（Q1=B / Q2=A / Q3=A / Q4=边界）：
- 无 execute（有 verify）→ verify 全部重路由为 execute（防御性重路由；修复 REAL-17
  「无物可验 → verdict_fail」）；仅此一种重路由，不新增动词规则（防误伤真 verify）；
- 悬空依赖（指向不存在 fragment / 自身）→ 机械剥离（依赖永远无法满足——剥离防
  编排器必然 `unsatisfied deps` 死锁失败）；
- 交付物重叠（两个 execute 节点共享交付物）→ 仅强注记（Q2=A：不自动合并——改
  DAG/依赖风险高）；
- 弱连通分量 > 1 → 仅注记（信息性）。

`lint_fragments` 只读（不动入参）；`apply_shape_lint` 返回修复后的 frags 副本 +
findings + 注记（空串 = 无信号——零行为）。
"""
from __future__ import annotations


def _deliverable_overlaps(items: list) -> list:
    """两个 execute 节点共享交付物 → [{a,b,item}]（按首次出现顺序）。"""
    owner: dict = {}
    out: list = []
    for f in items:
        if str(f.get("domain") or "") != "execute":
            continue
        fid = str(f.get("fragment_id") or "")
        for d in (f.get("deliverables") or []):
            key = str(d)
            if not key:
                continue
            if key in owner and owner[key] != fid:
                out.append({"a": owner[key], "b": fid, "item": key})
            else:
                owner[key] = fid
    return out


def _components(items: list) -> int:
    """弱连通分量数（仅计非强制节点——`_forced` 引擎脚手架只作连接器，
    孤立不计分量；星形（模型节点均挂 forced plan）不噪声）。空列表 → 0。"""
    ids = [str(f.get("fragment_id") or "") for f in items]
    if not ids:
        return 0
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    id_set = set(ids)
    for fid, f in zip(ids, items):
        for d in (f.get("deps") or []):
            ds = str(d)
            if ds in id_set and ds != fid:
                ra, rb = find(fid), find(ds)
                if ra != rb:
                    parent[ra] = rb
    counted = [fid for fid, f in zip(ids, items) if not f.get("_forced")]
    return len({find(i) for i in counted})


def _dep_closure(items: list, start: str) -> set:
    """从 start 出发的依赖闭包（含自身；忽略悬空/自环）——E0-2/A1 用。"""
    by_id = {str(f.get("fragment_id") or ""): f for f in items}
    seen: set = set()
    stack = [str(start)]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        node = by_id.get(cur)
        if node is None:
            continue
        for d in (node.get("deps") or []):
            ds = str(d)
            if ds != cur:
                stack.append(ds)
    return seen


def _depends_on(items: list, start: str, target: str) -> bool:
    """start 的依赖闭包是否可达 target（用于锚定环安全）——E0-2/A1 用。"""
    target = str(target)
    return target in (_dep_closure(items, start) - {str(start)})


def _unanchored_verify_ids(items: list) -> list:
    """依赖闭包内无 execute 的 verify（非 _forced）id 列表——E0-2/A1。

    无执行上游的 verify 会在 execute 产出前执行 → 判「产物缺失→不通过」
    （matrix-multiply 假阴机制）——需锚定到 execute 之后。
    """
    by_id = {str(f.get("fragment_id") or ""): f for f in items}
    out: list = []
    for f in items:
        if str(f.get("domain") or "") != "verify" or f.get("_forced"):
            continue
        fid = str(f.get("fragment_id") or "")
        ancestors = _dep_closure(items, fid) - {fid}
        has_exec = any(
            str((by_id.get(x) or {}).get("domain") or "") == "execute"
            for x in ancestors)
        if not has_exec:
            out.append(fid)
    return out


def lint_fragments(frags: list) -> dict:
    """只读 lint：发现项字典（不修改入参）。"""
    items = list(frags or [])
    ids = [str(f.get("fragment_id") or "") for f in items]
    id_set = set(ids)
    domains = [str(f.get("domain") or "") for f in items]
    verify_ids = [i for i, f in zip(ids, items)
                  if str(f.get("domain") or "") == "verify"
                  and not f.get("_forced")]
    dangling: dict = {}
    for fid, f in zip(ids, items):
        bad = [str(d) for d in (f.get("deps") or [])
               if str(d) not in id_set or str(d) == fid]
        if bad:
            dangling[fid] = bad
    return {
        "has_execute": "execute" in domains,
        "no_execute": "execute" not in domains and bool(verify_ids),
        "reroute_ids": [],       # apply_shape_lint 填充（lint 只读不减信息）
        "dangling": dangling,
        "deliverable_overlaps": _deliverable_overlaps(items),
        "components": _components(items),
        "unanchored_verifies": _unanchored_verify_ids(items),
    }


def apply_shape_lint(frags: list) -> tuple:
    """lint + 防御性处置：返回 (frags', findings, note)。"""
    items = [dict(f) for f in (frags or [])]
    findings = lint_fragments(items)
    note_parts: list = []

    # ① 无 execute → verify 重路由（REAL-17；仅此一种重路由——Q4 边界）
    if findings["no_execute"]:
        reroute = [str(f.get("fragment_id")) for f in items
                   if str(f.get("domain") or "") == "verify"
                   and not f.get("_forced")]
        for f in items:
            if str(f.get("fragment_id")) in set(reroute):
                f["domain"] = "execute"
        findings["reroute_ids"] = reroute
        if reroute:
            note_parts.append("防御性重路由 verify→execute："
                              + "、".join(reroute) + "（全程无执行节点）")

    # ② 悬空依赖剥离（防必然死锁失败——Q3=A）
    if findings["dangling"]:
        for f in items:
            bad = findings["dangling"].get(str(f.get("fragment_id") or ""))
            if not bad:
                continue
            f["deps"] = [d for d in (f.get("deps") or [])
                         if str(d) not in set(bad)]
        note_parts.append("依赖剥离：" + "；".join(
            f"{k}→[{','.join(v)}]" for k, v in findings["dangling"].items()))

    # ③ verify 锚定（E0-2/A1）：无执行上游的 verify → 追加全部 execute 依赖
    #    （防决策型 verify 在产出前执行 → verdict_fail 前置否决任务）；
    #    环安全：execute 若（传递）依赖该 verify 则排除（防成环）。
    unanchored = _unanchored_verify_ids(items)
    anchored: dict = {}
    skipped: list = []
    findings["verify_anchored"] = anchored
    if unanchored:
        exec_ids = [str(f.get("fragment_id") or "") for f in items
                    if str(f.get("domain") or "") == "execute"
                    and not f.get("_forced")]
        for f in items:
            fid = str(f.get("fragment_id") or "")
            if fid not in set(unanchored):
                continue
            safe = [eid for eid in exec_ids
                    if eid != fid and not _depends_on(items, eid, fid)]
            if not safe:
                skipped.append(fid)
                continue
            f["deps"] = list(dict.fromkeys(list(f.get("deps") or []) + safe))
            anchored[fid] = safe
        if anchored:
            note_parts.append(
                "verify 锚定：" + "；".join(
                    f"{k}→[{','.join(v)}]" for k, v in anchored.items())
                + "（无执行上游——防前置否决）")
        if skipped:
            note_parts.append("verify 锚定跳过：" + "、".join(skipped)
                              + "（执行均依赖它——防环）")

    # ④ 交付物重叠（E3-1/R1）：声明重叠 → 串行依赖边（链式——防并行并写覆盖；
    #    环安全：反向依赖已在则跳过并注记）；重路由后重算（域已定）
    overlaps = _deliverable_overlaps(items)
    findings["deliverable_overlaps"] = overlaps
    serialized: list = []
    skipped_cycle: list = []
    owner: dict = {}
    for f in items:
        if str(f.get("domain") or "") != "execute":
            continue
        fid = str(f.get("fragment_id") or "")
        for d in (f.get("deliverables") or []):
            key = str(d or "")
            if not key:
                continue
            prev = owner.get(key)
            if prev and prev != fid:
                if _depends_on(items, fid, prev):
                    pass  # 已串行（零行为）
                elif _depends_on(items, prev, fid):
                    skipped_cycle.append({"a": prev, "b": fid, "item": key})
                else:
                    f["deps"] = list(dict.fromkeys(
                        list(f.get("deps") or []) + [prev]))
                    serialized.append({"a": prev, "b": fid, "item": key})
            owner[key] = fid
    findings["overlap_serialized"] = serialized
    for o in serialized:
        note_parts.append(
            f"交付物重叠：{o['a']}×{o['b']}（{o['item']}）——已串行化"
            f"（{o['b']} 依赖 {o['a']}）")
    for o in skipped_cycle:
        note_parts.append(
            f"交付物重叠：{o['a']}×{o['b']}（{o['item']}）——反向依赖已在："
            "环安全跳过（仅注记）")

    # ⑤ 连通性（仅注记）
    if findings["components"] > 1:
        note_parts.append(f"弱连通分量 {findings['components']} 个——留意孤立节点")

    note = "[拆分质量] " + "；".join(note_parts) if note_parts else ""
    return items, findings, note
