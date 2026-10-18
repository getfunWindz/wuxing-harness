"""技能自动创建（2026-09-05：经验沉淀——失败案例→技能草稿→用户确认落盘）。

企业级「Skills 自我进化」第三环（自动创建）。第一版机制裁决：确定性模板沉淀
（不依赖 LLM 生成——诚实标注）；落盘需用户确认（人工介入哲学）。
"""
import pathlib
from dataclasses import dataclass

DOMAIN_NOTES = {
    "plan": "规划域失败常见于：方案未覆盖执行细节、验收标准缺失。实践：先列步骤与验收，再动手。",
    "execute": "执行域失败常见于：预算/轮数耗尽（探索型输出未及时收口）、工具超时。实践：优先写产物再收口。",
    "verify": "验证域失败常见于：未给出明确结论、未读取真实产物。实践：先读产物再给『结论：通过/不通过』。",
    "user": "用户域失败常见于：验收视角未落到可测条款。实践：把体验要求写成可验证条目。",
}


@dataclass
class SkillDraft:
    name: str
    description: str
    body: str
    level: str = "fragment"


def find_failed_domains(units: list, threshold: int = 2) -> list:
    """同域失败单元 ≥ threshold → 建议沉淀技能（按失败次数降序）。"""
    counts = {}
    for u in units:
        if getattr(u, "status", "") == "failed":
            counts[u.domain_id] = counts.get(u.domain_id, 0) + 1
    return [d for d, _ in sorted(counts.items(), key=lambda kv: -kv[1])
            if counts[d] >= threshold]


def suggest_skill(domain: str, errors: list) -> SkillDraft:
    """确定性模板草稿（归因+域最佳实践——失败案例的知识化）。"""
    err_summary = "；".join(str(e).split(":")[0].strip() for e in errors[:5])
    note = DOMAIN_NOTES.get(domain, "沉淀该域常见失败模式与应对实践。")
    body = (
        f"## 本技能沉淀什么\n"
        f"来自本工作区 {domain} 域的失败案例（{err_summary}）。\n\n"
        f"## 最佳实践\n{note}\n\n"
        f"## 失败时检查清单\n"
        f"- 1. 是否在预算内及时收口（避免探索型输出）\n"
        f"- 2. 是否满足域契约（markers + 物证）\n"
        f"- 3. 失败可归因（contract/tool/budget/provider）——provider 抖动不怪模型\n"
    )
    return SkillDraft(
        name=f"{domain}-failure-playbook",
        description=f"守护{domain}域执行质量的实践清单（经验沉淀）",
        body=body,
    )


def draft_to_dir(user_dir: pathlib.Path, draft: SkillDraft) -> pathlib.Path:
    """草稿落盘（用户级 skills/<name>/SKILL.md）——调用方负责用户确认。"""
    from wuxing.skills import install_skill
    sk_md = (f"---\nname: {draft.name}\ndescription: {draft.description}\n"
             f"level: {draft.level}\n---\n{draft.body}")
    return install_skill(user_dir=user_dir, name=draft.name,
                         description=draft.description, sk_md=sk_md)


# =============================== M3-1 LLM 版草稿生成 =========================
_SKETCH_SYSTEM = (
    "你是技能生成器。根据给定域与失败描述，输出 SKILL.md 草案（必须严格含 "
    "frontmatter：name/description/level，正文为最佳实践）。只输出 SKILL.md 内容。"
)


def validate_draft(raw: str) -> SkillDraft | None:
    """结构校验：frontmatter 可解析（name/description 非空）→ SkillDraft；否则 None。"""
    text = str(raw or "")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fm = {}
    body_lines = []
    in_fm = True  # 首行 --- 开启 frontmatter
    for ln in lines[1:]:
        if ln.strip() == "---":
            in_fm = False
            continue
        if in_fm and ":" in ln:
            k, v = ln.split(":", 1)
            fm[k.strip()] = v.strip().strip("\"'")
        elif not in_fm and ln.strip():
            body_lines.append(ln)
    name = fm.get("name", "")
    desc = fm.get("description", "")
    if not name or not desc:
        return None
    return SkillDraft(name=name, description=desc,
                      body="\n".join(body_lines),
                      level=fm.get("level", "fragment"))


def llm_sketch_skill(llm, domain: str, errors: list) -> SkillDraft:
    """LLM 生成草稿（失败案例语义提炼）——不合格回退模板版（机制不依赖模型）。

    M3-1：模板版为基线（确定性诚实）；LLM 版提升草稿质量（贴近真实失败模式）；
    落盘仍需用户确认（人工介入哲学不变）。
    """
    case = f"域：{domain}\n失败描述：{'；'.join(str(e)[:120] for e in errors[:8])}"
    try:
        raw = llm.chat([
            {"role": "system", "content": _SKETCH_SYSTEM},
            {"role": "user", "content": case},
        ])
    except Exception:
        raw = ""
    d = validate_draft(raw)
    if d is not None:
        return d
    return suggest_skill(domain, errors)
