"""技能自进化（用户裁决 2026-09-12——默认开）：任务高效 → 自评审沉淀 skill。

参考 DSH / WorkBuddy 形式：模型自评审「任务中的处理方式是否高效」，高效即
沉淀为技能（SKILL.md → 用户级 skills 目录），供后续任务 load_skill 复用。

机制裁决（防劣化 + 防污染）：
  1. 双确认——机械证据闸（全单元 ok + 任务 done）+ LLM 自评审；
  2. 沉淀失败/异常一律静默返回（技能是优化不是生命线）；
  3. 同名不覆盖（幂等；人工可删）；
  4. 正文要求可迁移方法论（不含具体任务数据——prompt 约束）。
"""
import json
import logging
import pathlib
import re

logger = logging.getLogger(__name__)

_REVIEW_SYSTEM = (
    "你是技能自进化评审器。判断给定任务的处理方式是否**高效且可复用**："
    "只有（高效 + 可迁移）同时成立才沉淀。严格输出 JSON（无多余文字）："
    '{"efficient": true|false, "reason": "一句话",'
    ' "skill": {"name": "kebab-case-name", "description": "何时用+做什么",'
    ' "body": "## 用法\\n..."}}\n'
    "沉淀纪律：\n"
    "1. 形态=类级技能（可迁移的方法论/步骤/检查清单），不是一会话一技能、"
    "不是任务叙事；\n"
    "2. 若本次处理已被现有技能覆盖（或与现有技能重复）→ 不要沉淀"
    "（同名不覆盖由机制强制执行；用户消息附有现役技能清单——先对照，"
    "已被覆盖即不沉淀）；\n"
    "3. description 必须同时写清「何时用」（触发条件）与「做什么」（能力）。\n"
    "不要沉淀（负面清单）：环境依赖故障（缺二进制/未配置凭据/路径不存在）、"
    "工具负面断言（如「某工具不可用」——会硬化成自我拒绝）、会话内瞬态错误、"
    "一次性任务叙事、未解决失败或未经验证的尝试（不得包装成可靠流程）。"
)


def efficiency_evidence(units: list, status: str) -> dict | None:
    """机械证据闸：全单元 ok + 任务 done → 证据；否则 None（不评审、零成本）。"""
    if status != "done" or not units:
        return None
    if any(getattr(u, "status", "") != "ok" for u in units):
        return None
    return {"units": len(units),
            "domains": sorted({getattr(u, "domain_id", "") for u in units})}


_MAX_REVIEW_SKILLS = 80
_CARD_DESC_MAX = 200


def _skill_cards_section(cards: list) -> str:
    lines = []
    for s in list(cards)[:_MAX_REVIEW_SKILLS]:
        desc = " ".join(str(s.get("description", "")).split())
        if len(desc) > _CARD_DESC_MAX:
            desc = desc[:_CARD_DESC_MAX] + "…"
        lines.append(f"- {s.get('name', '')}: {desc}")
    return ("# 现役技能（去重用；已覆盖本次处理则不要沉淀）\n"
            + "\n".join(lines))


def build_review_messages(task_text: str, units: list, evidence: dict,
                          skill_cards: list | None = None) -> list:
    """自评审输入：任务 + 处理概览 + 机械证据（不含具体产物内容——轻量）。

    skill_cards：现役技能清单（name+description）——软层去重（让提示词里
    「已覆盖则不沉淀」可执行）；None/空 → 不追加段（向后兼容）。
    """
    lines = [f"- [{getattr(u, 'domain_id', '?')}] {getattr(u, 'unit_id', '?')}"
             f" → {getattr(u, 'status', '?')}"
             f"（产物 {len(getattr(u, 'artifacts', []) or [])}）" for u in units]
    user = (f"# 任务\n{task_text}\n\n# 处理概览\n" + "\n".join(lines)
            + f"\n\n# 机械证据\n{json.dumps(evidence, ensure_ascii=False)}")
    if skill_cards:
        user += "\n\n" + _skill_cards_section(skill_cards)
    return [{"role": "system", "content": _REVIEW_SYSTEM},
            {"role": "user", "content": user}]


def _extract_json(text) -> dict:
    s = str(text or "")
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("judge 输出不含 JSON 对象")
    return json.loads(s[i:j + 1])


def _safe_name(name: str) -> str:
    """LLM 草稿名 kebab 化（E2-1：与 install_skill 契约对齐）：非 [a-z0-9] 折叠为
    '-'，截断 40，去边界 '-'。"""
    n = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
    return n[:40].rstrip("-")


def review_and_distill(task_text: str, units: list, status: str, llm,
                       skills_dir) -> dict:
    """高效任务 → 自评审 → 沉淀技能（失败静默；同名不覆盖）。

    返回 {"installed": bool, "name": str, "reason": str}。
    """
    ev = efficiency_evidence(units, status)
    if ev is None:
        return {"installed": False, "name": "", "reason": "no-efficiency-evidence"}
    cards = None
    try:
        from wuxing.skill_curator import load_skills
        cards = load_skills(skills_dir)
    except Exception as exc:  # 清单读取失败不注入（软层失效不阻断沉淀链）
        logger.debug("现役技能清单读取失败（不注入）：%s", exc)
    try:
        out = llm.chat(build_review_messages(task_text, units, ev,
                                             skill_cards=cards))
        text = out.text if hasattr(out, "text") else out
        data = _extract_json(text)
    except Exception as exc:
        return {"installed": False, "name": "",
                "reason": f"review-error: {type(exc).__name__}"}
    if not data.get("efficient"):
        return {"installed": False, "name": "",
                "reason": str(data.get("reason", "not-efficient"))[:200]}
    sk = data.get("skill") or {}
    name = _safe_name(sk.get("name", ""))
    desc = str(sk.get("description", "")).strip()
    body = str(sk.get("body", "")).strip()
    if not name or not desc or not body:
        return {"installed": False, "name": "", "reason": "invalid-skill-draft"}
    target = pathlib.Path(skills_dir) / name / "SKILL.md"
    if target.exists():
        return {"installed": False, "name": name, "reason": "exists"}
    try:
        from wuxing.skill_curator import find_near_duplicate
        near = find_near_duplicate(skills_dir, name=name, body=body)
    except Exception as exc:  # 查重故障放行安装（技能非生命线——fail-open）
        logger.debug("近义查重异常（放行安装）：%s", exc)
        near = None
    if near is not None:
        return {"installed": False, "name": name,
                "reason": f"near-duplicate:{near['name']}",
                "duplicate_of": near["name"],
                "duplicate_description": near.get("description", ""),
                "name_j": near["name_j"], "body_j": near["body_j"]}
    try:
        from wuxing.skills import install_skill
        sk_md = (f"---\nname: {name}\ndescription: {desc}\n"
                 f"level: fragment\n---\n{body}")
        install_skill(user_dir=pathlib.Path(skills_dir), name=name,
                      description=desc, sk_md=sk_md)
    except Exception as exc:
        return {"installed": False, "name": name,
                "reason": f"install-error: {type(exc).__name__}"}
    return {"installed": True, "name": name,
            "reason": str(data.get("reason", ""))[:200]}
