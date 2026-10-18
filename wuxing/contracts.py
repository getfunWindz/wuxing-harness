"""契约校验（P5 拆分：从 runner.py 提取——职责内聚，runner 瘦身）。

判定顺序（OR 语义——markers 命中即放行，schema 不覆盖）：
  1. 输出为合法 JSON 且通过 domain.output_schema 校验 → 通过
  2. 输出含域契约 success_markers（任一） → 通过
  3. 物证 AND 条件（require_write/require_read——P0 T3）
  4. 都不满足 → 本轮未收敛（继续循环/最终 failed）
"""
import json
import re

# 真测 REAL-10：结论必须锚定「结论+冒号+通过/不通过」形态（取最后一次）——
# 子串判定会把「（不构成不通过）」等非结论性字样误判为验收失败。
_CONCLUSION_RE = re.compile(
    r"结论[^：:\n]{0,8}[：:]\s*[\"'`（(]*\s*(通过|不通过)")


def _last_conclusion(text) -> str:
    """最后一条结论（无 → None）——回复/文件共用的判定口径。"""
    last = None
    for m in _CONCLUSION_RE.finditer(str(text or "")):
        last = m.group(1)
    return last


# P0-1b（评估 A 兜底）：结构化验收条目——`#n：通过｜不通过｜存疑｜证据：…`。
# 行首锚定（可带 bullet/引用前缀）——正文引用不得参与裁决（REAL-9 纪律同源）。
_ITEM_RE = re.compile(
    r"^[ \t>*\-]{0,4}#\s*(\d+)\s*[：:]\s*(通过|不通过|存疑)", re.MULTILINE)


def _structured_verdict(text) -> str | None:
    """结构化条目裁决：任一条目『不通过』→ 不通过；有条目但无不通过 → 通过；
    无条目 → None（回退结论锚定口径——向后兼容）。

    分层语义（评估 A）：存疑/范围外发现不阻断；仅验收项不通过/产物缺失才失败。
    """
    items = _ITEM_RE.findall(str(text or ""))
    if not items:
        return None
    return "不通过" if any(v == "不通过" for _, v in items) else "通过"


def _fallback_result_text(domain, logs, deliverables) -> str:
    """真测 REAL-13(a)：模型无收口文本（纯工具轮）时的交棒摘要。

    空产物会导致下游 verify 只有路径没有正文——回退「交付物清单 + 工具链摘录」，
    保证验收有据可依（不代替模型结论，仅作事实交棒）。
    """
    dels = [str(p) for p in (deliverables or []) if str(p)]
    tool_lines = [str(x) for x in (logs or [])
                  if str(x).startswith(("[tool", "[guard", "[warn"))]
    lines = ["# 交付摘要（模型无收口文本——自动生成）", "",
             f"- 域：{getattr(domain, 'domain_id', '')}",
             "- 交付物：" + ("、".join(f"`{p}`" for p in dels)
                                if dels else "（无）"),
             "- 工具链（尾部摘录）："]
    lines += [f"  - {t[:200]}" for t in tool_lines[-12:]]
    return "\n".join(lines)


def _read_deliverables_text(ws, deliverables: list) -> str:
    """B1：读取验收结论文件文本（倒序最多 3 个可读文件——头 4000 字符）。"""
    parts = []
    for p in reversed(list(deliverables or [])):
        if len(parts) >= 3:
            break
        try:
            content = ws.read(p)
        except Exception:
            content = None
        if content:
            parts.append(content[:4000])
    return "\n".join(parts)


# O3/C1（2026-10-07）：声称-交付物一致性——收敛文本中**反引号包裹**的路径型
# 声称（保守口径：正文裸路径不提取——防散文误伤）；核验结果经 out-param 回报，
# 不改变通过语义（软观测档——数据后硬化，见 O3-D1）。
_CLAIM_PATH_RE = re.compile(r"`([^`\n]{1,180}?\.[A-Za-z0-9]{1,8})`")


def _extract_claims(out: str) -> list:
    """O3/C1：提取反引号路径型声称（排除空格/URL/重复——保守口径）。"""
    seen, claims = set(), []
    for m in _CLAIM_PATH_RE.finditer(str(out or "")):
        p = m.group(1).strip()
        if " " in p or "://" in p or p in seen:
            continue
        seen.add(p)
        claims.append(p)
    return claims


def _missing_claims(ws, claims, deliverables) -> list:
    """O3/C1：声称路径 ∉ deliverables 且工作区不可读 ⇒ missing（异常 ⇒ 跳过不判）。"""
    known = {str(p).replace("\\", "/") for p in (deliverables or [])}
    missing = []
    for c in claims:
        if str(c).replace("\\", "/") in known:
            continue
        try:
            if ws is not None and ws.read(c) is not None:
                continue
        # 读取异常（越界/IO）⇒ 跳过不判（不得把不可读误报为缺件）
        except Exception:  # noqa: S112
            continue
        missing.append(c)
    return missing


def contract_check(domain, out: str, unit_id: str, artifacts: list,
                   logs: list, write_ok: bool, read_ok: bool,
                   ws=None, deliverables=None,
                   require_run: bool = False, run_ok: bool = True,
                   claim_report: list | None = None):
    """契约校验：返回 UnitResult（通过）或 None（未收敛）。

    ws：产物写入（通过时写收口产物——原 runner._contract_check 行为）。
    deliverables：本单元写工具产出路径（B1——verify 结论文件判定原料）。
    require_run/run_ok（真测缺陷 RT5）：碎片显式要求运行 pytest 时，
    必须有一次成功的 pytest 运行物证（输出含 passed 且无 failed/error）。
    claim_report（O3/C1 软观测）：execute 域通过时，将收敛文本中声称但未检出
    的产物路径 extend 入表（不改变通过语义——由调用方留痕/提醒）。
    """
    from wuxing.protocols import Artifact, UnitResult

    kind = domain.artifact_kind if domain.artifact_kind else domain.domain_id
    if not domain.success_markers:
        return None  # 域契约未定义 markers → 不判收敛（缺域防静默失败）
    passed = any(m in out for m in domain.success_markers)
    # M1-5/v4-flash 实测：写物证 = 完成充分证据（thinking 模型工具轮无文本——
    # 事实产出 > 自报声明；质量把关由 verify 域承担）。
    # 域范围：产物型域（plan/result——artifact_kind 非判定语义域）；
    # verify/acceptance 保持 marker 必需（结论语义——质量域）
    if not passed and write_ok and domain.artifact_kind in ("plan", "result"):
        passed = True
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            passed = passed or validate_schema(data, domain.output_schema)
    except (json.JSONDecodeError, ValueError):
        pass  # 非 JSON → markers 判定
    # B1（真实测试 F3 证据链）：verify 结论文件判定——v4-flash 工具轮无文本，
    # 模型把「结论：通过/不通过」写进验收文件（此前只能预算耗尽 failed）。
    # S4：扩展 user 域（acceptance 语义——文件含 markers 即收敛——B1 同构）。
    # 判定：语义域 + 写了文件 + 文件内容满足域语义（verify=含结论；user=含 markers）
    # → 按文件判定（不放水：内容不符仍不判）。
    _file_verdict = None  # "pass"/"fail"/None
    _file_passed = False
    if (domain.domain_id in ("verify", "user") and write_ok
            and ws is not None and deliverables):
        _text = _read_deliverables_text(ws, deliverables)
        if domain.domain_id == "verify":
            _concl = _last_conclusion(_text)
            if _concl:
                _file_passed = True
                _file_verdict = "fail" if _concl == "不通过" else "pass"
        elif _text and any(m in _text for m in domain.success_markers):
            _file_passed = True
    if _file_passed:
        passed = True
    # A1 修复（2026-09-07 审查 B6/M3）：物证闸**统一后置**——markers/JSON/schema
    # 任何通过路径都必须满足域要求的写/读物证（此前只拦 markers 路径：
    # JSON {result:...} 输出可绕过『写物证=完成前提』——机制裁决失效）
    # B1 补充（novice-2 根因）：文件结论路径豁免 read 物证——验收结论文件的
    # 产出本身=验收行为证据（否则「只写不读」的模型永远被 require_read 拦回）。
    if passed:
        if domain.require_write and not write_ok:
            passed = False
        if domain.require_read and not read_ok and not _file_passed:
            passed = False
        if require_run and not run_ok:
            passed = False  # RT5：要求运行 pytest 则须有成功运行物证
    if passed:
        # L0-4（审查 B6）：验收结论「不通过」→ 单元完成但标记 verdict_fail（
        # 任务级聚合不得判 done——validate 结论与任务状态分离）。
        # B1：文件结论优先（模型把结论写文件时）。
        if domain.domain_id == "verify":
            _items_verdict = _structured_verdict(out)
            if _items_verdict is not None:
                # P0-1b：结构化条目优先（机械化裁决）——存疑/额外发现不阻断
                verdict_fail = (_items_verdict == "不通过")
            else:
                _out_concl = _last_conclusion(out)
                if _out_concl is not None:
                    verdict_fail = (_out_concl == "不通过")
                elif _file_verdict is not None:
                    verdict_fail = (_file_verdict == "fail")
                else:
                    verdict_fail = False
        else:
            verdict_fail = False
    else:
        verdict_fail = False
    if passed:
        artifacts.append(Artifact(path=f"{unit_id}-{kind}.md",
                                  kind=kind, producer_unit=unit_id,
                                  schema_hint=domain.output_schema))
        if ws is not None:
            # 真测 REAL-13(a)：空文本（纯工具轮）→ 回退交付摘要（防 verify 饥饿）
            content = str(out or "").strip()
            if not content:
                content = _fallback_result_text(domain, logs, deliverables)
            ws.write_artifact(artifacts[-1], content)
        # O3/C1（软观测）：声称-交付物一致性——通过后只回报；仅 execute 域、
        # 有收口文本时提取（回退摘要/空文本不参与——无声称）
        if (claim_report is not None and domain.domain_id == "execute"
                and str(out).strip()):
            claim_report.extend(_missing_claims(ws, _extract_claims(out),
                                                deliverables))
        return UnitResult(unit_id=unit_id, domain_id=domain.domain_id,
                          status="ok", artifacts=artifacts, logs=logs,
                          verdict_fail=verdict_fail)
    return None


def validate_schema(data: dict, schema: dict) -> bool:
    # 2026-10-03 裁定（消除 docstring×实现不一致）：
    # - schema 为空 → True（无 schema 可校验，跳过——不阻断）
    # - 校验通过 → True
    # - 数据不符 / jsonschema 缺失 → False（该路径不贡献通过；不否决 markers/物证路径）
    # 历史：原 docstring「无 jsonschema → True（不阻断）」源于 28c0b32 的覆盖语义
    # （JSON dict 时 schema 结果覆盖关键词判定——True 意为「不否决关键词」）；
    # 现为 OR 语义（contract_check：passed = passed or validate_schema(...)），
    # False 已不否决任何路径——若缺失库时返回 True，等于未校验即放行（fail-open），
    # 违背机制裁决原则，故维持 False 并修正文档。
    """JSON Schema 校验（OR 判定的一路——True 表示本路径证明收敛）。"""
    if not schema:
        return True
    try:
        import jsonschema
        jsonschema.validate(data, schema)
        return True
    except Exception:
        # 无法校验（jsonschema 缺失——mcp 依赖链之外的精简环境）或校验不符：
        # 不虚发放行，也不否决 markers/物证等其他判定路径。
        return False
