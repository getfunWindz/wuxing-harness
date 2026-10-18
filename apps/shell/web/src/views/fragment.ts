/** 碎片会话视图（批 3 · 2026-09-21；后半程 · 2026-09-22）：碎片 = 独立会话——
 *  与主会话同渲染语汇（用户任务气泡 / LLM 输出助手气泡 / `[tool]` 工具行 / 系统提示折叠）。
 *  后半程新增：运行期实时切片（按 unit 过滤；绑定 run 全量——折叠规则同主会话）、
 *  绑定轮次（碎片内提交的会话轮）、输入区（复用 composer——输入/提交/停止/技能/参考 chips）。
 *  历史只读来源：`GET /unit-sessions/{unit}`（seed/thinking/done 行组 + bound_rounds）。 */
import type { UnitSessionDto } from "../protocol/generated.ts";
import type { ComponentInstance } from "../render/component.ts";
import { h } from "../render/dom.ts";
import { createFold } from "../render/fold.ts";
import {
  createComposer,
  type ComposerInstance,
  type ComposerProps,
} from "../components/composer.ts";
import { t } from "./i18n.ts";
import {
  deriveBoundRoundItems,
  deriveFragmentConversation,
  deriveFragmentLive,
  deriveThinkingSummary,
  type FragmentItem,
  type FragmentLiveInput,
} from "./view-model.ts";

export interface FragmentProps {
  unitId: string;
  session: UnitSessionDto | null;
  /** 实时切片输入（由 main 装配；null = 无活动任务数据） */
  live: FragmentLiveInput | null;
  /** 输入区（null = 不渲染——如 boot 前） */
  composer: ComposerProps | null;
  /** 实时 chips 点击（进入另一个碎片会话；当前 unit 自身不响应） */
  onOpenFragment?(unitId: string): void;
  onBack(): void;
}

export function createFragment(
  host: HTMLElement,
  initial: FragmentProps,
): ComponentInstance<FragmentProps> {
  let props = initial;
  let composer: ComposerInstance | null = null;
  const root = h("section", { class: "fragment", dataset: { st: "fragment" } });
  const header = h("header", { class: "fragment-head" });
  const body = h("div", { class: "fragment-body", dataset: { st: "fragment-body" } });
  const composerHost = h("div", {
    class: "fragment-composer", dataset: { st: "fragment-composer" },
  });
  root.append(header, body, composerHost);
  host.appendChild(root);

  const bubble = (
    cls: string,
    text: string,
    st: string,
    artifacts: readonly string[] = [],
  ): HTMLElement =>
    h("div", { class: `chat-msg ${cls}`, dataset: { st } },
      h("div", { class: "chat-bubble" },
        h("div", { class: "chat-text", text }),
        artifacts.length > 0
          ? h("div", { class: "chat-refs" },
              ...artifacts.slice(0, 5).map((p) => h("span", { class: "chat-ref", text: p })))
          : null));

  const itemNode = (m: FragmentItem, i: number): HTMLElement => {
    if (m.kind === "system") {
      // Wave-2 T8：details → fold 原语（统一折叠动画）
      const fold = createFold({
        head: h("button", {
          class: "fragment-system-head", attrs: { type: "button" },
          text: t("fragment.system"),
        }),
        body: h("div", { class: "fragment-system-body", text: m.text }),
      });
      fold.root.classList.add("fragment-system");
      return fold.root;
    }
    if (m.kind === "think") {
      // 思维链暴露（2026-09-21）：与主会话同逻辑——默认折叠、可展开；摘要=首行
      const line = deriveThinkingSummary([{ unitId: props.unitId, round: 0, text: m.text }], false);
      // Wave-2 T8：details → fold（默认折叠、可展开）
      const fold = createFold({
        head: h("button", {
          class: "think-head", attrs: { type: "button" },
          text: line ?? t("stream.thinking"),
        }),
        body: h("div", { class: "think-body", text: m.text }),
      });
      fold.root.classList.add("think-block");
      fold.root.dataset.st = `frag-think:${String(i)}`;
      return fold.root;
    }
    if (m.kind === "status") {
      return h("div", { class: "fragment-status-row", dataset: { st: "fragment-status" }, text: m.text });
    }
    if (m.kind === "tool") return bubble("chat-tool", m.text, "fragment-tool");
    if (m.kind === "user") return bubble("chat-user", m.text, "fragment-user");
    return bubble("chat-assistant", m.text, "fragment-assistant", m.artifacts ?? []);
  };

  /** 单元状态文案（与主会话 stream 同口径）。 */
  const unitStatusLabel = (status: string): string => {
    if (status === "ok") return t("status.done");
    if (status === "failed") return t("status.failed");
    if (status === "confirm") return t("status.pending");
    return t("status.running");
  };

  const statusDot = (status: string): string => {
    if (status === "ok") return "ok";
    if (status === "failed" || status === "rejected") return "bad";
    if (status === "cancelled") return "";
    return "run";
  };

  /** 实时切片（2026-09-22）：过程组 + 并行 chips + 思维链 + 单元行——折叠规则同主会话。 */
  const liveNode = (live: NonNullable<ReturnType<typeof deriveFragmentLive>>): HTMLElement => {
    const summary = h("button", {
      class: "round-summary", dataset: { st: "fragment-process-summary" },
      attrs: { type: "button" },
      text: live.running
        ? t("stream.processRunning", { steps: String(live.steps) })
        : t("stream.processSummary", { steps: String(live.steps) }),
    });
    const chips = h("div", {
      class: "frag-chip-row", dataset: { st: "fragment-chip-row" },
    });
    chips.hidden = live.chips.length === 0;
    chips.replaceChildren(...live.chips.map((chip) => h("span", {
      class: "frag-chip", dataset: { st: `fragment-chip:${chip.unitId}` },
      attrs: { title: `${chip.domain} · ${chip.label}` },
      onClick: () => {
        if (chip.unitId !== props.unitId) props.onOpenFragment?.(chip.unitId);
      },
    },
      h("span", { class: "dom-tag", text: chip.domain }),
      h("span", { text: chip.label }))));
    const thinkHost = h("div", { class: "round-think" },
      ...live.thoughts.map((thought) => {
        const fold = createFold({
          head: h("button", {
            class: "think-head", attrs: { type: "button" },
            text: deriveThinkingSummary([thought], thought.open) ?? t("stream.thinking"),
          }),
          body: h("div", { class: "think-body", text: thought.text }),
          open: thought.open,
        });
        fold.root.classList.add("think-block");
        fold.root.dataset.st = `frag-live-think:${thought.unitId}`;
        return fold.root;
      }));
    const rowsHost = h("div", { class: "stream-rows" },
      ...live.rows.map((row) => h("section", {
        class: "unit-card",
        dataset: { unit: row.unitId, status: row.status, st: `frag-live-unit:${row.unitId}` },
      },
        h("header", { class: "frag-head" },
          h("span", { class: "dom-tag", text: row.domainId }),
          h("span", { class: "unit-id", text: row.unitId }),
          h("span", { class: "frag-status card-status" },
            h("i", { class: `dot ${statusDot(row.status)}` }),
            unitStatusLabel(row.status))),
        h("div", { class: "frag-body" },
          h("div", { class: "frag-state", text: row.detail !== "" ? row.detail : t("stream.waiting") })))));
    const wrap = h("div", { class: "round round-live", dataset: { st: "fragment-live" } });
    if (live.showUser) wrap.append(bubble("chat-user", live.userText, "fragment-live-user"));
    const liveFold = createFold({
      head: summary,
      body: h("div", { class: "round-process-body" }, chips, thinkHost, rowsHost),
      open: live.running,
    });
    liveFold.root.classList.add("round-process");
    liveFold.root.dataset.st = "fragment-process";
    wrap.append(liveFold.root);
    return wrap;
  };

  const paint = (): void => {
    const meta = (props.session?.meta ?? {}) as Record<string, unknown>;
    const bits = [
      String(meta.domain ?? ""),
      String(meta.status ?? ""),
      String(meta.key ?? "") === "" ? "" : `key ${String(meta.key)}`,
      Number(meta.reuse ?? 0) > 0 ? `${t("fragment.reuse")} ${String(meta.reuse)}` : "",
    ].filter((s) => s !== "");
    const headNodes: HTMLElement[] = [
      h("button", {
        class: "btn ghost small",
        attrs: { type: "button", "data-st": "fragment-back" },
        text: t("fragment.back"),
        onClick: () => { props.onBack(); },
      }),
      // 精化（2026-09-23）：碎片会话标识（FSC 可延续标志）——其余与主会话工作区一致
      h("span", {
        class: "fragment-badge", dataset: { st: "fragment-badge" },
        attrs: { title: t("fragment.badge.title") },
        text: t("fragment.badge"),
      }),
      h("span", { class: "fragment-title", text: props.unitId }),
    ];
    if (bits.length > 0) {
      headNodes.push(h("span", { class: "fragment-meta", text: bits.join(" · ") }));
    }
    header.replaceChildren(...headNodes);

    // 历史（碎片自身会话文件组）+ 绑定轮次（碎片内提交的会话轮）+ 实时切片
    const items: FragmentItem[] = [
      ...deriveFragmentConversation(props.session?.groups ?? []),
      ...deriveBoundRoundItems(props.session?.bound_rounds ?? []),
    ];
    const nodes = items.map(itemNode);
    const live = props.live !== null ? deriveFragmentLive(props.live) : null;
    if (live !== null) nodes.push(liveNode(live));
    body.replaceChildren(...(nodes.length === 0
      ? [h("div", { class: "fragment-empty", text: t("fragment.empty") })]
      : nodes));

    // 输入区（全量对齐：输入/提交/停止/技能/参考 chips——复用 composer）
    if (props.composer !== null) {
      composerHost.hidden = false;
      if (composer === null) composer = createComposer(composerHost, props.composer);
      else composer.update(props.composer);
    } else {
      composerHost.hidden = true;
      if (composer !== null) {
        composer.dispose();
        composer = null;
      }
    }
  };
  paint();

  const update = (next: FragmentProps): void => {
    const changed = next.unitId !== props.unitId
      || next.session !== props.session
      || next.live !== props.live
      || next.composer !== props.composer
      || next.onBack !== props.onBack
      || next.onOpenFragment !== props.onOpenFragment;
    props = next;
    if (changed) paint();
  };
  return {
    update,
    dispose(): void {
      composer?.dispose();
      root.remove();
    },
  };
}
