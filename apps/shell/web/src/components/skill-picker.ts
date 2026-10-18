/** 技能选择器（2026-09-19 用户裁决）：会话框下方线性图标 → 技能列表，支持多选。
    共享渲染：已选技能 chips + 弹层（全量技能，复选式）。提交时由 main 注入前缀。 */
import { h } from "../render/dom.ts";
import { t } from "../views/i18n.ts";

export interface SkillEntry {
  readonly name: string;
  readonly description: string;
  /** E2-1（B5）：调用策略——缺省视为 true（旧载荷/旧技能兼容）。 */
  readonly enabled?: boolean;
  readonly model_invocable?: boolean;
  readonly user_invocable?: boolean;
}

/** 用户可选技能（E2-1 · B5）：仅 enabled 且 user_invocable（缺省 true）。
    停用与「仅模型」技能不出现在选择器；管理面仍可见。 */
export function userSelectableSkills<T extends SkillEntry>(skills: readonly T[]): T[] {
  return skills.filter((s) => s.enabled !== false && s.user_invocable !== false);
}

/** 仅用户技能正文块（E2-1 · J5）：剥离 frontmatter，包装技能名。
    用于 submit 前注入任务文本（机制注入——该技能模型不可 load_skill）。 */
export function skillContentBlock(name: string, content: string): string {
  const body = content.replace(/^---\s*\n[\s\S]*?\n---\s*\n?/, "").trim();
  return `【技能：${name}】\n${body}`;
}

/** 已选技能 chips（带移除 ×）。 */
export function skillChips(
  selected: readonly string[],
  onRemove: (name: string) => void,
): HTMLElement[] {
  return selected.map((name) =>
    h("span", { class: "skill-chip on", attrs: { "data-st": `skill-chip:${name}`, title: name } },
      name,
      h("button", {
        attrs: { type: "button", "data-st": `skill-del:${name}`, title: t("composer.removeSkill") },
        text: "×",
        onClick: () => { onRemove(name); },
      })));
}

/** 技能弹层（多选；列表由 main 载入后经 props 传入）。 */
export function skillPicker(props: {
  skills: readonly SkillEntry[];
  selected: readonly string[];
  onToggle(name: string): void;
}): HTMLElement {
  return h("div", { class: "skill-pop", attrs: { "data-st": "skill-pop" } },
    h("div", { class: "skill-pop-head", text: t("composer.skillTitle") }),
    props.skills.length === 0
      ? h("div", { class: "skill-pop-empty", text: t("composer.skillsEmpty") })
      : h("div", { class: "skill-pop-body" }, ...props.skills.map((skill) => {
        const on = props.selected.includes(skill.name);
        return h("button", {
          class: on ? "skill-pop-item on" : "skill-pop-item",
          attrs: { type: "button", "data-st": `skill-pick:${skill.name}`, title: skill.description },
          onClick: () => { props.onToggle(skill.name); },
        },
          h("span", { class: on ? "sp-check on" : "sp-check" }),
          h("span", { class: "sp-main" },
            h("span", { class: "sp-name", text: skill.name }),
            h("span", { class: "sp-desc", text: skill.description })));
      })));
}
