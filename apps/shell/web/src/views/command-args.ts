/** E2-UI：扩展命令参数表单（逐字段输入——不出现整段 JSON 裸输入；Esc/遮罩关闭）。
    —— 字段来自命令声明的 args（ExtCommandArgDto）；校验/转换经 command-args-model。 */
import type { ExtCommandArgDto } from "../protocol/generated.ts";
import { h, mount, svgIcon } from "../render/dom.ts";
import { ICON_CLOSE } from "./icons.ts";
import { t } from "./i18n.ts";
import {
  collectArgValues,
  initialArgDraft,
  type ArgDraft,
  type ArgError,
} from "./command-args-model.ts";

export interface CommandArgsOptions {
  /** 显示标题（命令描述或名称）。 */
  title: string;
  schema: readonly ExtCommandArgDto[];
  onSubmit(values: Record<string, unknown>): void;
  onCancel?(): void;
}

function errText(arg: ExtCommandArgDto, code: ArgError): string {
  return code === "required"
    ? t("cmd.args.err.required")
    : t("cmd.args.err.type", { type: arg.type });
}

export function openCommandArgs(host: HTMLElement, opts: CommandArgsOptions): void {
  const draft: ArgDraft = initialArgDraft(opts.schema);
  let errors: Record<string, ArgError> = {};
  const overlay = h("div", { class: "modal-overlay",
                             attrs: { "data-st": "cmd-args", role: "dialog",
                                      "aria-modal": "true", "aria-label": t("cmd.args.title", { name: opts.title }) } });
  const fields = h("div", { class: "cmd-args-fields" });

  function close(notify: boolean): void {
    document.removeEventListener("keydown", onKey);
    overlay.remove();
    if (notify) opts.onCancel?.();
  }
  function onKey(ev: KeyboardEvent): void {
    if (ev.key === "Escape") close(true);
  }

  const paint = (): void => {
    mount(fields, ...opts.schema.map((arg) => {
      const err = errors[arg.name];
      let control: HTMLElement;
      if (arg.type === "bool") {
        const box = h("input", {
          attrs: { type: "checkbox", "data-st": `cmd-arg:${arg.name}`,
                   id: `cmd-arg-${arg.name}`, name: `cmd-arg-${arg.name}` },
        }) as HTMLInputElement;
        box.checked = draft[arg.name] === true;
        box.addEventListener("change", () => { draft[arg.name] = box.checked; });
        control = h("label", { class: "cmd-arg-bool" }, box,
                    h("span", { text: t("cmd.args.on") }));
      } else {
        const input = h("input", {
          class: "st-input",
          attrs: {
            type: arg.type === "str" ? "text" : "number",
            ...(arg.type === "float" ? { step: "any" } : {}),
            "data-st": `cmd-arg:${arg.name}`,
            id: `cmd-arg-${arg.name}`, name: `cmd-arg-${arg.name}`,
          },
        }) as HTMLInputElement;
        input.value = String(draft[arg.name] ?? "");
        input.addEventListener("input", () => { draft[arg.name] = input.value; });
        control = input;
      }
      return h("div", { class: "cmd-arg" },
        h("div", { class: "cmd-arg-label" },
          h("span", { text: arg.label }),
          arg.required
            ? h("span", { class: "cmd-arg-req", text: t("cmd.args.required") })
            : null),
        control,
        err
          ? h("div", {
              class: "st-err",
              attrs: { "data-st": `cmd-arg-err:${arg.name}` },
              text: errText(arg, err),
            })
          : null);
    }));
  };

  const submit = (): void => {
    const out = collectArgValues(opts.schema, draft);
    errors = out.errors;
    if (Object.keys(errors).length > 0) { paint(); return; }
    close(false);
    opts.onSubmit(out.values);
  };

  overlay.appendChild(h("div", { class: "modal-card cmd-args-card" },
    h("div", { class: "modal-head" },
      h("b", { text: t("cmd.args.title", { name: opts.title }) }),
      h("button", {
        class: "modal-x",
        attrs: { type: "button", "data-st": "cmd-args-close" },
        onClick: () => { close(true); },
      }, svgIcon(ICON_CLOSE))),
    h("div", { class: "modal-body" }, fields),
    h("div", { class: "cmd-args-foot" },
      h("button", {
        class: "st-btn ghost",
        attrs: { type: "button", "data-st": "cmd-args-cancel" },
        text: t("cmd.args.cancel"),
        onClick: () => { close(true); },
      }),
      h("button", {
        class: "st-btn",
        attrs: { type: "button", "data-st": "cmd-args-submit" },
        text: t("cmd.args.submit"),
        onClick: submit,
      }))));
  overlay.addEventListener("click", (ev) => {
    if (ev.target === overlay) close(true);
  });
  document.addEventListener("keydown", onKey);
  host.appendChild(overlay);
  paint();
  overlay.querySelector<HTMLInputElement>('[data-st^="cmd-arg:"]')?.focus();
}
