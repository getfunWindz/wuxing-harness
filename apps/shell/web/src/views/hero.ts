/** 欢迎页（外观复现 A8）：大 LOGO + 中英渐隐大字 + 引导输入卡 + 示例 chips。
    仅零态（无任务）显示；工作态由 main（hero-mode）隐藏。
    大 LOGO 仅此处出现（用户裁决 2026-09-18）；顶栏副标常驻。 */
import { h, mount, svgIcon } from "../render/dom.ts";
import type { ComponentInstance } from "../render/component.ts";
import { createBrand, mountBrandDust, mountBrandEtch } from "../components/brand.ts";
import { isOutsideWorkspace, shouldSubmit } from "./view-model.ts";
import { loadDraft, saveDraft } from "./draft.ts";
import { ICON_CLIP, ICON_RETURN, ICON_SKILL } from "./icons.ts";
import { computeTextareaHeight } from "./hero-size.ts";
import { t } from "./i18n.ts";

import { skillChips, skillPicker, type SkillEntry } from "../components/skill-picker.ts";

export interface HeroProps {
  hasWorkspace: boolean;
  examples: readonly string[];
  references: readonly string[];
  skills: readonly SkillEntry[];
  selectedSkills: readonly string[];
  /** M7 B2（CP-1）：草稿持久化键（工作区 id） */
  draftKey: string;
  /** M7 B4（#3）：外部参考文件徽标判定（当前工作区路径） */
  workspacePath: string;
  /** M7 #8（A3）：重启后挂起任务（快照 pending_resume）——零态恢复入口 */
  pendingResume: { readonly taskText: string } | null;
  onResumePending(): void;
  onAbandonPending(): void;
  onSubmit(text: string): void;
  onPickFiles(): void;
  onRemoveRef(path: string): void;
  onToggleSkill(name: string): void;
  onSkillsOpen(): void;
  onCreateWorkspace(): void;
  /** E3-1/R5（T5）：隔离运行开关（可选——向后兼容） */
  isolateRun?: boolean;
  onToggleIsolate?(): void;
  /** T-6：首用引导条（零态且未记账时显示） */
  onboard: boolean;
  onDismissOnboard(): void;
  onOpenHelp(): void;
}

const NS = "http://www.w3.org/2000/svg";

/** 大 LOGO（官方美学：双梅「暗香」· 平色版，用户裁决 2026-09-19）。 */
function createLogo(): SVGElement {
  const el = (tag: string, attrs: Record<string, string>): SVGElement => {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    return node;
  };
  const svg = el("svg", { viewBox: "0 0 120 120", width: "96", height: "96", "aria-hidden": "true" });
  svg.appendChild(el("path", { d: "M 8 116 C 26 104 30 92 44 80 C 56 70 54 60 64 50 C 76 38 90 32 112 28", fill: "none", stroke: "#23211e", "stroke-width": "5", "stroke-linecap": "round" }));
  svg.appendChild(el("path", { d: "M 8 116 C 18 110 24 102 28 94", fill: "none", stroke: "#23211e", "stroke-width": "2.6", "stroke-linecap": "round" }));
  svg.appendChild(el("path", { d: "M 48 76 C 42 68 34 64 22 62", fill: "none", stroke: "#23211e", "stroke-width": "2.6", "stroke-linecap": "round" }));
  svg.appendChild(el("path", { d: "M 76 40 C 80 30 88 26 100 26", fill: "none", stroke: "#23211e", "stroke-width": "2.2", "stroke-linecap": "round" }));
  const main = el("g", { transform: "translate(88,42)" });
  for (let k = 0; k < 5; k++) {
    const petal = el("ellipse", { cx: "0", cy: "-12.5", rx: "6.4", ry: "9", fill: "#a53f33" });
    if (k > 0) petal.setAttribute("transform", `rotate(${k * 72} 0 0)`);
    main.appendChild(petal);
  }
  const stamens = el("g", { stroke: "#23211e", "stroke-width": "0.9", fill: "none" });
  const stamenPaths = ["M 0 -1.5 L 0 -8", "M 1.8 -0.8 L 6.8 -3.6", "M 1 1.8 L 4.8 5.6", "M -1 1.8 L -4.8 5.6", "M -1.8 -0.8 L -6.8 -3.6"];
  for (const d of stamenPaths) stamens.appendChild(el("path", { d }));
  main.appendChild(stamens);
  const dots = el("g", { fill: "#23211e" });
  const dotPos: ReadonlyArray<readonly [string, string]> = [["0", "-8"], ["6", "-3.2"], ["3.7", "5"], ["-3.7", "5"], ["-6", "-3.2"]];
  for (const [cx, cy] of dotPos) dots.appendChild(el("circle", { cx, cy, r: "1.05" }));
  main.appendChild(dots);
  svg.appendChild(main);
  const side = el("g", { transform: "translate(42,68) rotate(-30)" });
  for (let k = 0; k < 3; k++) {
    const petal = el("ellipse", { cx: "0", cy: "-9.5", rx: "5.8", ry: "7.6", fill: "#b25056" });
    if (k > 0) petal.setAttribute("transform", `rotate(${k * 120} 0 0)`);
    side.appendChild(petal);
  }
  side.appendChild(el("circle", { cx: "0", cy: "0", r: "2.1", fill: "#23211e" }));
  svg.appendChild(side);
  svg.appendChild(el("circle", { cx: "102", cy: "24", r: "3", fill: "#a53f33" }));
  svg.appendChild(el("circle", { cx: "20", cy: "60", r: "2.6", fill: "#a53f33" }));
  return svg;
}

export type HeroInstance = ComponentInstance<HeroProps> & {
  /** 批 4：预填输入区（承接简报——用户确认后发送） */
  setText(value: string): void;
};

export function createHero(host: HTMLElement, initial: HeroProps): HeroInstance {
  let props = initial;
  let examplesSig = "";
  let composing = false;
  let skillsOpen = false;

  const ta = document.createElement("textarea");
  ta.className = "hero-text";
  ta.id = "hero-text";
  ta.name = "task-input";
  ta.rows = 1;
  ta.placeholder = t("hero.placeholder");

  const autoGrow = (): void => {
    // Wave-2 T4：隐藏态不量测（Bug#4——0 高度压扁占位符；null=保持上次合法值）
    const h = computeTextareaHeight({
      visible: !host.hidden && root.offsetParent !== null,
      scrollHeight: ta.scrollHeight,
      max: 200,
    });
    if (h !== null) ta.style.height = h;
  };
  ta.addEventListener("input", () => { autoGrow(); saveDraft(props.draftKey, ta.value); });
  ta.addEventListener("compositionstart", () => { composing = true; });
  ta.addEventListener("compositionend", () => { composing = false; });

  const send = (): void => {
    if (!props.hasWorkspace) { props.onCreateWorkspace(); return; }
    const text = ta.value.trim();
    if (text === "") return;
    props.onSubmit(text);
    ta.value = "";
    autoGrow();
    saveDraft(props.draftKey, "");
  };
  ta.addEventListener("keydown", (ev) => {
    const keyboard = ev as KeyboardEvent;
    if (shouldSubmit({ key: keyboard.key, shiftKey: keyboard.shiftKey, isComposing: composing })) {
      keyboard.preventDefault();
      send();
    }
  });

  // 静态文案元素（语言切换由 applyStaticTexts 重设——占位符与文案随语言更新）
  const noteText = h("span", { class: "hero-note-text" });
  const noteBtn = h("button", {
    class: "btn small", attrs: { type: "button", "data-st": "hero-create-ws" },
    text: t("hero.createWs"),
    onClick: () => { props.onCreateWorkspace(); },
  });
  const note = h("div", { class: "hero-note" }, noteText, noteBtn);
  const tagEl = h("p", { class: "hero-tag" });
  const hintEl = h("span", { class: "hero-hint" });
  const clipBtn = h("button", {
    class: "chip-btn icon-btn",
    attrs: { type: "button", "data-st": "hero-ref" },
    onClick: () => { props.onPickFiles(); },
  }, svgIcon(ICON_CLIP, 17));
  const sendBtn = h("button", {
    class: "btn-send",
    attrs: { type: "button", "data-st": "hero-send" },
    onClick: send,
  }, svgIcon(ICON_RETURN, 22));

  // T-6：首用三步引导条（稳定节点——文案随语言重设，显隐随 props）
  const onboardTitle = h("span", { class: "ho-title" });
  const onboardStep1 = h("span", { class: "ho-step" });
  const onboardStep2 = h("span", { class: "ho-step" });
  const onboardStep3 = h("span", { class: "ho-step" });
  const onboardHelpBtn = h("button", {
    class: "btn small ghost",
    attrs: { type: "button", "data-st": "onboard-help" },
    onClick: () => { props.onOpenHelp(); },
  });
  const onboardDismissBtn = h("button", {
    class: "btn small",
    attrs: { type: "button", "data-st": "onboard-dismiss" },
    onClick: () => { props.onDismissOnboard(); },
  });
  const onboardHost = h("div", { class: "hero-onboard", attrs: { "data-st": "hero-onboard" } },
    onboardTitle, onboardStep1, onboardStep2, onboardStep3,
    onboardHelpBtn, onboardDismissBtn);

  const examples = h("div", { class: "hero-examples" });
  const chips = h("div", { class: "cskills hero-cskills" });
  const popHost = h("div", { class: "skill-pop-host" });
  const skillBtn = h("button", {
    class: "chip-btn icon-btn",
    attrs: { type: "button", "data-st": "hero-skill", title: t("composer.skillTitle"), "aria-label": t("composer.skillTitle") },
    onClick: () => {
      skillsOpen = !skillsOpen;
      if (skillsOpen) props.onSkillsOpen();
      paint();
    },
  }, svgIcon(ICON_SKILL, 17));

  // E3-1/R5（T5）：隔离运行开关（hero 零态与 composer 同口径）
  const isolateBtn = h("button", {
    class: "chip-btn",
    attrs: { type: "button", "data-st": "hero-isolate",
             "data-on": "0", title: t("composer.isolateTitle") },
    text: t("composer.isolate"),
    onClick: () => { props.onToggleIsolate?.(); },
  }) as HTMLButtonElement;

  function paint(): void {
    mount(chips,
      ...skillChips(props.selectedSkills, (name) => { props.onToggleSkill(name); }),
      ...props.references.map((path) => {
        const parts = path.split(/[\\/]/);
        const name = parts[parts.length - 1] || path;
        const outside = isOutsideWorkspace(path, props.workspacePath);
        return h("span", {
          class: outside ? "skill-chip ref out" : "skill-chip ref",
          attrs: { "data-st": `hero-ref-chip:${path}`, title: path },
        },
          name,
          outside
            ? h("span", { class: "ref-out-badge", text: t("composer.refExternal") })
            : null,
          h("button", {
            attrs: { type: "button", "data-st": `hero-ref-del:${path}` },
            text: "×",
            onClick: () => { props.onRemoveRef(path); },
          }));
      }));
    chips.hidden = chips.childElementCount === 0;
    mount(popHost, ...(skillsOpen
      ? [skillPicker({
        skills: props.skills,
        selected: props.selectedSkills,
        onToggle: (name) => { props.onToggleSkill(name); },
      })]
      : []));
    skillBtn.title = t("composer.skillTitle");
    const pr = props.pendingResume;
    pendingCard.hidden = pr === null;
    pendingCard.replaceChildren(...(pr === null
      ? []
      : [
          h("div", { class: "hero-pending-title", text: t("hero.pendingTitle") }),
          h("div", { class: "hero-pending-text", text: pr.taskText }),
          h("div", { class: "hero-pending-actions" },
            h("button", {
              class: "btn small primary",
              attrs: { type: "button", "data-st": "hero-pending-resume" },
              text: t("hero.pendingResume"),
              onClick: () => { props.onResumePending(); },
            }),
            h("button", {
              class: "btn small ghost",
              attrs: { type: "button", "data-st": "hero-pending-abandon" },
              text: t("hero.pendingAbandon"),
              onClick: () => { props.onAbandonPending(); },
            })),
        ]));
  }

  const pendingCard = h("div", {
    class: "hero-pending", attrs: { "data-st": "hero-pending" },
  });

  const root = h("section", { class: "hero" },
    h("div", { class: "hero-logo" }, createLogo()),
    h("div", { class: "hero-brand" }, createBrand("hero")),
    tagEl,
    onboardHost,
    h("div", { class: "hero-input" },
      chips,
      popHost,
      ta,
      h("div", { class: "hero-actions" },
        clipBtn,
        skillBtn,
        isolateBtn,
        hintEl,
        sendBtn)),
    pendingCard,
    note,
    examples);
  host.appendChild(root);

  // 外点关闭技能弹层
  const onDocPointer = (ev: PointerEvent): void => {
    if (!skillsOpen) return;
    if (root.contains(ev.target as Node)) return;
    skillsOpen = false;
    paint();
  };
  document.addEventListener("pointerdown", onDocPointer, true);

  /** 静态文案随语言重设（每次 update 调用——onLangChange → render → hero.update）。 */
  const applyStaticTexts = (): void => {
    ta.placeholder = t("hero.placeholder");
    tagEl.textContent = t("hero.tag");
    hintEl.textContent = t("hero.hint");
    noteText.textContent = t("hero.noWorkspace");
    noteBtn.textContent = t("hero.createWs");
    clipBtn.title = t("composer.attach");
    clipBtn.setAttribute("aria-label", t("composer.attach"));
    sendBtn.title = t("composer.send");
    sendBtn.setAttribute("aria-label", t("composer.send"));
    skillBtn.title = t("composer.skillTitle");
    skillBtn.setAttribute("aria-label", t("composer.skillTitle"));
    isolateBtn.textContent = t("composer.isolate");
    isolateBtn.title = t("composer.isolateTitle");
    onboardTitle.textContent = t("onboard.title");
    onboardStep1.textContent = t("help.step1");
    onboardStep2.textContent = t("help.step2");
    onboardStep3.textContent = t("help.step3");
    onboardHelpBtn.textContent = t("onboard.help");
    onboardDismissBtn.textContent = t("onboard.dismiss");
  };

  const update = (next: HeroProps): void => {
    const draftSwitched = next.draftKey !== props.draftKey;
    props = next;
    applyStaticTexts();
    isolateBtn.dataset.on = next.isolateRun === true ? "1" : "0";
    note.hidden = next.hasWorkspace;
    onboardHost.hidden = !next.onboard;
    if (draftSwitched) {
      ta.value = loadDraft(next.draftKey);
      autoGrow();
    }
    paint();
    const sig = next.examples.join("|");
    if (sig !== examplesSig) {
      examplesSig = sig;
      examples.replaceChildren(...next.examples.map((text) =>
        h("button", {
          class: "chip-btn example", attrs: { type: "button" },
          text,
          onClick: () => { ta.value = text; autoGrow(); saveDraft(props.draftKey, text); ta.focus(); },
        })));
    }
    // Wave-2 T4：可见时重测（隐藏态自动跳过——切回新建会话不被 0 高度压扁）
    autoGrow();
  };
  update(initial);
  mountBrandDust(root);
  mountBrandEtch(root);
  autoGrow();

  return {
    update,
    setText(value: string): void {
      ta.value = value;
      saveDraft(props.draftKey, value);
      autoGrow();
      ta.focus();
    },
    dispose(): void {
      document.removeEventListener("pointerdown", onDocPointer, true);
      root.remove();
    },
  };
}
