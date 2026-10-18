/** 输入区组件：Enter 提交 / Shift+Enter 换行 / IME 组字守卫 / 参考文件 chips（P2-M6）
    + 技能选择（2026-09-19：线性图标 → 多选技能列表；提交时由 main 注入前缀）。 */
import { h, mount, svgIcon } from "../render/dom.ts";
import type { ComponentInstance } from "../render/component.ts";
import { isOutsideWorkspace, shouldSubmit } from "../views/view-model.ts";
import { loadDraft, saveDraft } from "../views/draft.ts";
import { ICON_CLIP, ICON_RETURN, ICON_SKILL } from "../views/icons.ts";
import { t } from "../views/i18n.ts";
import { skillChips, skillPicker, type SkillEntry } from "./skill-picker.ts";

export interface ComposerProps {
  disabled: boolean;
  running: boolean;
  references: readonly string[];
  skills: readonly SkillEntry[];
  selectedSkills: readonly string[];
  /** M7 B2（CP-1）：草稿持久化键（工作区 id） */
  draftKey: string;
  /** M7 B4（#3）：外部参考文件徽标判定（当前工作区路径） */
  workspacePath: string;
  onSubmit(text: string): void;
  onPickFiles(): void;
  onRemoveRef(path: string): void;
  onToggleSkill(name: string): void;
  onSkillsOpen(): void;
  onStop(): void;
  /** E3-1/R5（T5）：隔离运行开关（可选——向后兼容） */
  isolateRun?: boolean;
  onToggleIsolate?(): void;
}

/** 组件实例 + 输入区控制面（P2-M6：重试回填 / 聚焦）。 */
export type ComposerInstance = ComponentInstance<ComposerProps> & {
  setText(value: string): void;
  getText(): string;
  focus(): void;
};

function baseName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

export function createComposer(
  host: HTMLElement,
  initial: ComposerProps,
): ComposerInstance {
  let props = initial;
  let composing = false;
  let skillsOpen = false;

  const textarea = document.createElement("textarea");
  textarea.id = "composer-text";
  textarea.name = "composer-input";
  textarea.rows = 1;
  textarea.placeholder = t("composer.placeholder");
  textarea.setAttribute("aria-label", t("a11y.composer"));
  textarea.dataset.focusKey = "composer";

  /** 自适应高度（旧壳 composer.js autoGrow：上限 336px；超出滚动——CSS overflow-y:auto）。 */
  const autoGrow = (): void => {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 336)}px`;
  };
  textarea.addEventListener("input", () => { autoGrow(); saveDraft(props.draftKey, textarea.value); });

  const refsHost = h("div", { class: "cskills" });
  const popHost = h("div", { class: "skill-pop-host" });
  const attach = h("button", {
    class: "chip-btn icon-btn",
    attrs: { type: "button", "data-st": "composer-attach", title: t("composer.attach"), "aria-label": t("composer.attach") },
    onClick: () => { props.onPickFiles(); },
  }, svgIcon(ICON_CLIP, 17));
  const skillBtn = h("button", {
    class: "chip-btn icon-btn",
    attrs: { type: "button", "data-st": "composer-skill", title: t("composer.skillTitle"), "aria-label": t("composer.skillTitle") },
    onClick: () => {
      skillsOpen = !skillsOpen;
      if (skillsOpen) props.onSkillsOpen();
      paint();
    },
  }, svgIcon(ICON_SKILL, 17));

  // E3-1/R5（T5）：隔离运行开关（显式档——非 git 工作区由服务端 loud 拒绝）
  const isolateBtn = h("button", {
    class: "chip-btn",
    attrs: { type: "button", "data-st": "composer-isolate",
             "data-on": "0", title: t("composer.isolateTitle") },
    text: t("composer.isolate"),
    onClick: () => { props.onToggleIsolate?.(); },
  }) as HTMLButtonElement;

  const send = h("button", {
    class: "btn-send",
    attrs: { type: "button", "data-st": "composer-send", title: t("composer.send"), "aria-label": t("composer.send") },
  }, svgIcon(ICON_RETURN, 22)) as HTMLButtonElement;

  const stop = h("button", {
    class: "btn small ghost danger",
    attrs: { type: "button", "data-st": "composer-stop" },
    text: t("composer.stop"),
    onClick: () => { props.onStop(); },
  }) as HTMLButtonElement;
  stop.hidden = true;

  const tip = h("div", { class: "ctip" });
  const box = h("div", { class: "cbox" },
    refsHost,
    popHost,
    textarea,
    h("div", { class: "ctools" },
      attach,
      skillBtn,
      isolateBtn,
      h("span", { class: "grow" }),
      stop,
      send),
    tip);

  const root = h("div", { class: "composer" }, box);
  host.appendChild(root);

  // 外点关闭技能弹层
  const onDocPointer = (ev: PointerEvent): void => {
    if (!skillsOpen) return;
    if (root.contains(ev.target as Node)) return;
    skillsOpen = false;
    paint();
  };
  document.addEventListener("pointerdown", onDocPointer, true);

  const submit = (): void => {
    const text = textarea.value.trim();
    if (text === "" || props.disabled) return;
    props.onSubmit(text);
    textarea.value = "";
    autoGrow();
    saveDraft(props.draftKey, "");
  };

  textarea.addEventListener("compositionstart", () => { composing = true; });
  textarea.addEventListener("compositionend", () => { composing = false; });
  textarea.addEventListener("keydown", (event) => {
    const keyboard = event as KeyboardEvent;
    if (shouldSubmit({ key: keyboard.key, shiftKey: keyboard.shiftKey, isComposing: composing })) {
      keyboard.preventDefault();
      submit();
    }
  });
  send.addEventListener("click", submit);

  function paint(): void {
    mount(refsHost,
      ...props.selectedSkills.length > 0
        ? skillChips(props.selectedSkills, (name) => { props.onToggleSkill(name); })
        : [],
      ...props.references.map((path) => {
        const outside = isOutsideWorkspace(path, props.workspacePath);
        return h("span", {
          class: outside ? "skill-chip ref out" : "skill-chip ref",
          attrs: { "data-st": `ref:${path}`, title: path },
        },
          baseName(path),
          outside
            ? h("span", { class: "ref-out-badge", text: t("composer.refExternal") })
            : null,
          h("button", {
            attrs: { type: "button", "data-st": `ref-del:${path}` },
            text: "×",
            onClick: () => { props.onRemoveRef(path); },
          }));
      }));
    refsHost.hidden = refsHost.childElementCount === 0;
    mount(popHost, ...(skillsOpen
      ? [skillPicker({
        skills: props.skills,
        selected: props.selectedSkills,
        onToggle: (name) => { props.onToggleSkill(name); },
      })]
      : []));
  }

  const update = (next: ComposerProps): void => {
    const draftSwitched = next.draftKey !== props.draftKey;
    props = next;
    textarea.disabled = next.disabled;
    send.disabled = next.disabled;
    stop.hidden = !next.running;
    stop.textContent = t("composer.stop");
    textarea.placeholder = t("composer.placeholder");
    textarea.setAttribute("aria-label", t("a11y.composer"));
    attach.title = t("composer.attach");
    attach.setAttribute("aria-label", t("composer.attach"));
    skillBtn.title = t("composer.skillTitle");
    skillBtn.setAttribute("aria-label", t("composer.skillTitle"));
    isolateBtn.textContent = t("composer.isolate");
    isolateBtn.title = t("composer.isolateTitle");
    isolateBtn.dataset.on = next.isolateRun === true ? "1" : "0";
    if (draftSwitched) {
      textarea.value = loadDraft(next.draftKey);
      autoGrow();
    }
    paint();
  };
  update(initial);
  autoGrow();

  return {
    update,
    setText(value: string): void {
      textarea.value = value;
      saveDraft(props.draftKey, value);
      autoGrow();
      textarea.focus();
    },
    getText(): string {
      return textarea.value;
    },
    focus(): void {
      textarea.focus();
    },
    dispose(): void {
      document.removeEventListener("pointerdown", onDocPointer, true);
      root.remove();
    },
  };
}
