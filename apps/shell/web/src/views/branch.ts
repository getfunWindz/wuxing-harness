/** G1：对话分支弹层（模式/摘要/焦点——从既有轮派生新会话）。 */
import { h, mount } from "../render/dom.ts";
import { t } from "./i18n.ts";

export interface BranchDialogRequest {
  readonly fromRound: number;
  readonly mode: "redo" | "continue";
  readonly summary: "mech" | "llm" | "none";
  readonly focus: string;
}

export interface BranchDialogOptions {
  readonly round: number;
  onConfirm(req: BranchDialogRequest): Promise<void> | void;
}

let overlay: HTMLDivElement | null = null;

interface RadioItem {
  readonly value: string;
  readonly label: string;
  readonly checked?: boolean;
}

function radioGroup(name: string, items: readonly RadioItem[]): HTMLElement {
  return h("div", { class: "st-row" },
    ...items.map((item) =>
      h("label", { class: "st-radio" },
        h("input", {
          attrs: {
            type: "radio", name, value: item.value,
            id: `${name}-${item.value}`,
            ...(item.checked === true ? { checked: "checked" } : {}),
          },
        }),
        h("span", { text: item.label }))));
}

export function openBranchDialog(host: HTMLElement,
                                 options: BranchDialogOptions): void {
  closeBranchDialog();
  const root = h("div", { class: "prompt-overlay" }) as HTMLDivElement;
  overlay = root;
  const err = h("div", { class: "st-err", attrs: { hidden: "hidden" } });
  const focus = h("input", {
    class: "st-input",
    attrs: { type: "text", "data-st": "branch-focus",
             id: "branch-focus", name: "branch-focus",
             placeholder: t("branch.focus") },
  }) as HTMLInputElement;
  let busy = false;

  const readChecked = (name: string): string => {
    const el = root.querySelector(`input[name="${name}"]:checked`);
    return el instanceof HTMLInputElement ? el.value : "";
  };

  const submit = async (): Promise<void> => {
    busy = true;
    try {
      await options.onConfirm({
        fromRound: options.round,
        mode: readChecked("branch-mode") === "continue" ? "continue" : "redo",
        summary: (readChecked("branch-summary") || "mech") as
          "mech" | "llm" | "none",
        focus: focus.value.trim(),
      });
      closeBranchDialog();
    } catch (e) {
      err.textContent = e instanceof Error ? e.message : String(e);
      err.removeAttribute("hidden");
    } finally {
      busy = false;
    }
  };

  root.addEventListener("pointerdown", (ev) => {
    if (ev.target === root) closeBranchDialog();
  });
  mount(root,
    h("div", { class: "prompt-card", dataset: { st: "branch-dialog" } },
      h("div", { class: "st-fl",
                 text: t("branch.title", { round: String(options.round) }) }),
      h("div", { class: "st-fl", text: t("branch.mode") }),
      radioGroup("branch-mode", [
        { value: "redo", label: t("branch.mode.redo"), checked: true },
        { value: "continue", label: t("branch.mode.continue") },
      ]),
      h("div", { class: "st-fl", text: t("branch.summary") }),
      radioGroup("branch-summary", [
        { value: "mech", label: t("branch.summary.mech"), checked: true },
        { value: "llm", label: t("branch.summary.llm") },
        { value: "none", label: t("branch.summary.none") },
      ]),
      focus,
      err,
      h("div", { class: "st-row" },
        h("button", {
          class: "st-btn", attrs: { type: "button", "data-st": "branch-ok" },
          text: t("branch.ok"),
          onClick: () => { if (!busy) void submit(); },
        }),
        h("button", {
          class: "st-btn ghost",
          attrs: { type: "button", "data-st": "branch-cancel" },
          text: t("settings.prov.cancel"),
          onClick: () => { closeBranchDialog(); },
        }))));
  host.appendChild(root);
  focus.focus();
}

export function closeBranchDialog(): void {
  if (overlay !== null) {
    overlay.remove();
    overlay = null;
  }
}
