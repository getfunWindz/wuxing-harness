/** 技能安装表单预校验（A9 · v43-⑦）：与 `wuxing/skills.py::install_skill` 同规。
 *
 * 规则单一事实源 = 引擎（`install_skill` / `validate_skill_fields`）：
 *   - name 必填、kebab-case（≤40）、不得含路径分隔符/相对路径；
 *   - SKILL.md 必填且含合法 frontmatter（`---` 简单键值 `---`）；
 *   - frontmatter name/description 必填；name 与安装参数一致；
 *   - description 超长 / level 非法 = 告警（引擎行为：入索引 + loud 可见）。
 * 改动引擎规则时必须同步本文件（常量级 parity 由
 * `wuxing/tests/test_skill_form_parity.py` 守卫；行为由本文件旁测试锁定）。
 */

export const SKILL_NAME_MAX = 40;
export const SKILL_DESC_MAX = 500;
export const SKILL_NAME_RE = /^[a-z0-9][a-z0-9-]{0,39}$/;

const SKILL_LEVELS = ["domain", "fragment"] as const;

export interface SkillDraftCheck {
  readonly errors: readonly string[];
  readonly warnings: readonly string[];
}

/** 最小 frontmatter 解析（与引擎 `_parse_frontmatter` 同规）；破损返回 null（不猜测）。 */
export function parseSkillFrontmatter(text: string): Record<string, string> | null {
  const m = /^---\s*\n([\s\S]*?)\n---\s*(\n|$)/.exec(String(text ?? ""));
  if (!m) return null;
  const fm: Record<string, string> = {};
  for (const rawLine of (m[1] ?? "").split("\n")) {
    const line = rawLine.trim();
    if (line === "" || line.startsWith("#")) continue;
    const idx = line.indexOf(":");
    if (idx < 0) return null; // 非简单键值 → 视为破损
    fm[line.slice(0, idx).trim()] =
      line.slice(idx + 1).trim().replace(/^["']+|["']+$/g, "");
  }
  return fm;
}

/** 安装表单预校验（同一套拒收语义；errors 拦截提交，warnings 仅提示）。 */
export function validateSkillDraft(name: string, content: string): SkillDraftCheck {
  const errors: string[] = [];
  const warnings: string[] = [];
  const nm = String(name ?? "").trim();
  if (nm === "") {
    errors.push("name 必填");
  } else if (nm === "." || nm === ".." || nm.includes("/") || nm.includes("\\")) {
    errors.push(`非法技能名 ${JSON.stringify(nm)}（不得含路径分隔符/相对路径）`);
  } else if (!SKILL_NAME_RE.test(nm)) {
    errors.push(`非法技能名 ${JSON.stringify(nm)}（须 kebab-case，≤${SKILL_NAME_MAX}）`);
  }

  const md = String(content ?? "");
  if (md.trim() === "") {
    errors.push("SKILL.md 内容必填");
    return { errors, warnings };
  }
  const fm = parseSkillFrontmatter(md);
  if (fm === null) {
    errors.push("SKILL.md 缺少合法 frontmatter");
    return { errors, warnings };
  }
  const fmName = (fm["name"] ?? "").trim();
  if (fmName === "") {
    errors.push("name 必填");
  } else if (!SKILL_NAME_RE.test(fmName)) {
    errors.push(`name 非法（须 kebab-case，≤${SKILL_NAME_MAX}）：${JSON.stringify(fmName)}`);
  }
  const fmDesc = (fm["description"] ?? "").trim();
  if (fmDesc === "") {
    errors.push("description 必填");
  } else if (fmDesc.length > SKILL_DESC_MAX) {
    warnings.push(`description 超长（${fmDesc.length}>${SKILL_DESC_MAX}，索引截断显示）`);
  }
  const level = (fm["level"] ?? "").trim();
  if (level !== "" && !(SKILL_LEVELS as readonly string[]).includes(level)) {
    warnings.push(`level 非法（${JSON.stringify(level)}）——回落 fragment`);
  }
  if (nm !== "" && fmName !== "" && fmName !== nm) {
    errors.push(
      `frontmatter name 与安装参数不一致（${JSON.stringify(fmName)} != ${JSON.stringify(nm)}）`);
  }
  return { errors, warnings };
}

/** A14：技能详情「依赖工具」行文本（空 → ""，调用方条件渲染）。 */
export function skillToolsRows(detail: {
  readonly allowed_tools?: readonly string[];
  readonly allowed_tools_missing?: readonly string[];
}): { tools: string; missing: string } {
  const tools = (detail.allowed_tools ?? []).join(", ");
  const missing = (detail.allowed_tools_missing ?? []).join(", ");
  return { tools, missing };
}
