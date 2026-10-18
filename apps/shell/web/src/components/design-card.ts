/** 循迹设计卡片（双模式批 3 · 设计 §5/§7）：阶段/轮次/问题/地图 + 交接按钮。
 *
 * 可见性：活动会话为循迹模式且设计态在场（available）。问题带推荐答案；
 * 地图可用时提供「查看地图」与「交给执行」（软门——机制闸只看地图可用性）。
 *
 * Wave-2 T9（用户裁决 2026-10-01）：卡片折叠——
 *  - 默认策略：有待答票据 → 展开；只读态（无待答）→ 收起；
 *  - 开合记忆：会话内内存（Map<session, boolean>，不落盘；换会话记忆独立）；
 *  - 主 CTA（查看地图/交接）提升到 head 行右侧——收起时仍可达；
 *  - 展开体 = 票据/地图行/规格/实施票据（原 design-actions 已上提不重复）。
 */
import { h, mount } from "../render/dom.ts";
import type { ComponentInstance } from "../render/component.ts";
import { createFold } from "../render/fold.ts";
import { t } from "../views/i18n.ts";
import { hasRecommendLine, implTicketStatusKey, recommendLine } from "../views/view-model.ts";
import type { DesignTicketRow } from "../views/view-model.ts";

/** 会话内开合记忆（进程内内存——不落盘；用户裁决 2026-10-01）。 */
const foldMemory = new Map<string, boolean>();

/** 折叠状态解析（Wave-2 T9 纯函数——node:test 覆盖）：
 *  记忆优先（用户手动开合）；无记忆 → 默认策略（有待答展开 / 只读收起）。 */
export function resolveDesignCardOpen(
    session: string, hasPending: boolean,
    memo: ReadonlyMap<string, boolean>): boolean {
  const remembered = memo.get(session);
  return remembered === undefined ? hasPending : remembered;
}

/** 待答票据数（frontier——头部徽标；2026-10-16）。 */
export function pendingCount(tickets: readonly DesignTicketRow[]): number {
  return tickets.filter((t) => t.frontier).length;
}

export interface DesignCardProps {
  visible: boolean;
  phase: string;
  round: number;
  tickets: readonly DesignTicketRow[];
  mapReady: boolean;
  mapChanged: boolean;
  /** 规格指针（批 3）：null = 未生成/无工作区——整行不显示 */
  spec: { slug: string; ready: boolean; url: string } | null;
  /** 实施票据（批 4）：工作区级执行清单（proposed 待发布 / ready 已发布） */
  implTickets: readonly { id: string; title: string; status: string;
                          claimed_by: string; stale: boolean }[];
  /** Wave-2 T9：当前会话名（开合记忆键——换会话记忆独立）。 */
  session?: string;
  /** 输入框当前文本（派生每票据「已采用」态——由 main.ts 注入）。 */
  composerText: string;
  onViewMap(): void;
  onHandoff(): void;
  /** 采用/取消推荐（行级 toggle；由 main.ts 计算写入/回退）。 */
  onToggleRecommend(recommend: string): void;
  onPublishTickets(): void;
}

export type DesignCardInstance = ComponentInstance<DesignCardProps>;

export function createDesignCard(host: HTMLElement,
                                 initial: DesignCardProps): DesignCardInstance {
  let props = initial;
  const root = h("div", { class: "design-card-slot-inner" });
  host.appendChild(root);

  function paint(): void {
    root.hidden = !props.visible;
    if (!props.visible) {
      mount(root);
      return;
    }
    const phaseLabel = t(`design.phase.${props.phase || "recon"}`);
    const pending = pendingCount(props.tickets);

    // —— head（按钮：标题/阶段/轮次/变更 badge + chevron） ——
    const head = h("button", {
      class: "fold-head design-head",
      attrs: { type: "button", "aria-expanded": "false" },
    },
      h("span", { class: "fold-chevron", text: "▸" }),
      h("span", { class: "design-title", text: t("design.title") }),
      h("span", { class: "design-phase", dataset: { st: "design-phase" },
                  text: phaseLabel }),
      h("span", { class: "design-round", dataset: { st: "design-round" },
                  text: t("design.round", { n: props.round }) }),
      pending > 0
        ? h("span", { class: "design-pending",
                      dataset: { st: "design-pending-count" },
                      text: t("design.pendingCount", { n: pending }) })
        : null,
      props.mapChanged
        ? h("span", { class: "design-changed", dataset: { st: "design-map-changed" },
                      text: t("design.mapChanged") })
        : null);

    // —— 主 CTA（head 行右侧——收起时仍可达；foldToggle 在 fold 创建后追加） ——
    const mapBtn = props.mapReady
      ? h("button", {
          class: "st-btn ghost", attrs: { type: "button", "data-st": "design-map-open" },
          text: t("design.viewMap"),
          onClick: () => { props.onViewMap(); },
        })
      : null;
    const handoffBtn = props.mapReady && props.phase !== "ready"
      ? h("button", {
          class: "st-btn", attrs: { type: "button", "data-st": "design-handoff" },
          text: t("design.handoff"),
          onClick: () => { props.onHandoff(); },
        })
      : null;

    // —— 展开体（票据/地图/规格/实施票据） ——
    const body = h("div", { class: "design-card-body",
                            attrs: { id: "design-card-body" } },
      props.tickets.length > 0
        ? h("div", { class: "design-questions" },
            h("div", { class: "design-q-head", text: t("design.tickets") }),
            ...props.tickets.map((tk) =>
              h("div", {
                class: `design-q${tk.frontier ? "" : " blocked"}`,
                dataset: { st: `design-ticket:${tk.id || "legacy"}` },
              },
                h("div", { class: "design-q-text",
                           text: tk.id ? `[${tk.id}] ${tk.statement}` : tk.statement }),
                tk.blockedBy.length > 0
                  ? h("div", { class: "design-q-blocked",
                               text: t("design.blockedBy", { ids: tk.blockedBy.join("、") }) })
                  : null,
                tk.recommend !== ""
                  ? h("div", { class: "design-q-rec" },
                      h("span", { text: t("design.recommend", { text: tk.recommend }) }),
                      (() => {
                        const line = recommendLine(t("design.answerPrefix"),
                                                   tk.recommend);
                        const applied = hasRecommendLine(props.composerText, line);
                        return h("button", {
                          class: "st-btn ghost",
                          attrs: { type: "button",
                                   "data-st": `design-ticket-use:${tk.id || "legacy"}`,
                                   "aria-pressed": applied ? "true" : "false" },
                          text: applied ? t("design.cancelRecommend")
                                        : t("design.useRecommend"),
                          onClick: () => { props.onToggleRecommend(tk.recommend); },
                        });
                      })())
                  : null)))
        : null,
      h("div", { class: "design-map-row", dataset: { st: "design-map-status" },
                 text: props.mapReady ? t("design.mapReady") : t("design.mapMissing") }),
      props.spec !== null
        ? h("div", { class: "design-spec-row", dataset: { st: "design-spec-status" } },
            h("span", { text: t("design.specReady", { slug: props.spec.slug }) }),
            props.spec.ready
              ? h("a", {
                  class: "st-btn ghost",
                  attrs: { href: props.spec.url, target: "_blank", rel: "noopener",
                           "data-st": "design-spec-open" },
                  text: t("design.viewSpec"),
                })
              : null)
        : null,
      props.implTickets.length > 0
        ? h("div", { class: "design-tickets-impl",
                     dataset: { st: "design-impl-tickets" } },
            h("div", { class: "design-q-head", text: t("design.implTickets") }),
            ...props.implTickets.map((tk) =>
              h("div", { class: "design-q",
                         dataset: { st: `design-impl-ticket:${tk.id}` } },
                h("div", { class: "design-q-text",
                            text: `[${tk.id}] ${tk.title}`
                              + (tk.claimed_by
                                ? " · " + t("design.claimedBy", { by: tk.claimed_by })
                                  + (tk.stale ? t("design.claimStale") : "")
                                : "") }),
                h("span", { class: "design-q-rec",
                            text: t(implTicketStatusKey(tk.status)) }))),
            props.implTickets.some((tk) => tk.status === "proposed")
              ? h("button", {
                  class: "st-btn",
                  attrs: { type: "button", "data-st": "design-tickets-publish" },
                  text: t("design.publishTickets"),
                  onClick: () => { props.onPublishTickets(); },
                })
              : null)
        : null);

    // —— 折叠状态（T9）：记忆 > 默认策略（有待答展开 / 只读收起） ——
    const key = props.session ?? "";
    const hasPending = props.tickets.length > 0;
    const wantOpen = resolveDesignCardOpen(key, hasPending, foldMemory);
    const fold = createFold({
      head, body, open: wantOpen,
      onToggle: (open) => { foldMemory.set(props.session ?? "", open); },
    });
    // 显式开合按钮（入口显著；程序性 setOpen 不触发 onToggle——此处手动记账）
    const foldToggle = h("button", {
      class: "st-btn ghost design-fold-toggle",
      attrs: { type: "button", "data-st": "design-fold-toggle",
               "aria-controls": "design-card-body",
               "aria-expanded": wantOpen ? "true" : "false" },
      text: wantOpen ? t("design.fold") : t("design.unfold"),
      onClick: () => {
        const next = !fold.isOpen();
        fold.setOpen(next);
        foldMemory.set(props.session ?? "", next);
        foldToggle.textContent = next ? t("design.fold") : t("design.unfold");
        foldToggle.setAttribute("aria-expanded", next ? "true" : "false");
      },
    });
    const headActions = h("div", { class: "design-head-actions" },
      mapBtn, handoffBtn, foldToggle);
    fold.root.classList.add("design-card");
    fold.root.dataset.st = "design-card";
    // CTA 行插到 head 与 fold-body 之间（grid 布局：head 左 / CTA 右 / body 全宽）
    fold.root.insertBefore(headActions, fold.root.children[1] ?? null);
    mount(root, fold.root);
  }

  const update = (next: DesignCardProps): void => {
    props = next;
    paint();
  };
  update(initial);

  return {
    update,
    dispose(): void {
      root.remove();
    },
  };
}
