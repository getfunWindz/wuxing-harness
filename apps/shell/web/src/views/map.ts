/** 工作区地图只读视图（双模式批 3 · 设计 §5.4）：WUXING.md 受控段落渲染 + 打开文件/复制。 */
import type { MapViewDto } from "../protocol/generated.ts";
import { h, svgIcon } from "../render/dom.ts";
import { ICON_CLOSE } from "./icons.ts";
import { t } from "./i18n.ts";
import { routeProgress } from "./view-model.ts";

/** 复制摘要文本（目的地 + 路线——供外部粘贴；决策记录不包含）。 */
function mapSummary(dto: MapViewDto): string {
  return [dto.destination, ...dto.route].filter((s) => s !== "").join("\n");
}

/** 结构化决策行文本（批 2）：[D-n] 文本（理由）— 上游/取代/来源。 */
function decisionLine(d: MapViewDto["decisions"][number]): string {
  const head = d.id ? `[${d.id}] ${d.text}` : d.text;
  const why = d.why ? `（${d.why}）` : "";
  const meta = [
    d.upstream.length > 0 ? `上游 ${d.upstream.join("、")}` : "",
    d.supersedes.length > 0 ? `取代 ${d.supersedes.join("、")}` : "",
    d.source ? `来源 ${d.source}` : "",
  ].filter((s) => s !== "").join(" · ");
  return meta !== "" ? `${head}${why}  — ${meta}` : `${head}${why}`;
}

export function openMapView(host: HTMLElement, dto: MapViewDto,
                            fileUrl: string,
                            opts?: { onCopy?(text: string): void }): void {
  const overlay = h("div", { class: "modal-overlay",
                             attrs: { "data-st": "map-view", role: "dialog",
                                      "aria-modal": "true", "aria-label": t("map.title") } });

  function close(): void {
    document.removeEventListener("keydown", onKey);
    overlay.remove();
  }
  function onKey(ev: KeyboardEvent): void {
    if (ev.key === "Escape") close();
  }

  const sections: [string, readonly string[]][] = [
    [t("map.destination"), dto.destination ? [dto.destination] : []],
    [t("map.route"), dto.route],
    [t("map.decisions"), dto.decisions.map((d) => decisionLine(d))],
    [t("map.fog"), dto.fog],
    [t("map.outOfScope"), dto.out_of_scope],
  ];
  const prog = routeProgress(dto.route);
  overlay.appendChild(h("div", { class: "modal-card map-card" },
    h("div", { class: "modal-head" },
      h("b", { text: t("map.title") }),
      dto.available
        ? h("button", {
            class: "modal-x",
            attrs: { type: "button", "data-st": "map-copy" },
            text: t("map.copy"),
            onClick: () => { opts?.onCopy?.(mapSummary(dto)); },
          })
        : null,
      dto.available
        ? h("a", {
            class: "modal-x",
            attrs: { href: fileUrl, target: "_blank", rel: "noopener",
                     "data-st": "map-open-file" },
            text: t("map.openFile"),
          })
        : null,
      h("button", {
        class: "modal-x", attrs: { type: "button", "data-st": "map-close" },
        onClick: () => { close(); },
      }, svgIcon(ICON_CLOSE))),
    h("div", { class: "modal-body" },
      ...(dto.available
        ? [
            ...sections.map(([title, lines]) =>
              h("div", { class: "map-sec" },
                h("div", { class: "map-sec-title" },
                  title,
                  title === t("map.route") && prog !== null
                    ? h("span", {
                        class: "map-progress",
                        dataset: { st: "map-progress" },
                        text: t("map.progress", { done: prog.done,
                                                  total: prog.total }),
                      })
                    : null),
                lines.length > 0
                  ? h("div", { class: "map-sec-body" },
                      ...lines.map((l) => h("div", { class: "map-line", text: l })))
                  : h("div", { class: "map-sec-empty", text: "—" }))),
            h("div", { class: "map-hash",
                       text: dto.hash ? dto.hash.slice(0, 12) : "" }),
          ]
        : [h("div", { class: "map-sec-empty", text: t("map.empty") })]))));

  overlay.addEventListener("click", (ev) => { if (ev.target === overlay) close(); });
  document.addEventListener("keydown", onKey);
  host.appendChild(overlay);
}
