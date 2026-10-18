/** 任务流：keyed 单元行（尾更新）+ 确认门（单条/批量 + 理由 + 已决反馈）+ 结果。 */
import type { ConfirmDto, QuestionListDto } from "../protocol/generated.ts";
import { h, svgIcon } from "../render/dom.ts";
import { createFold, type FoldInstance } from "../render/fold.ts";
import { applyKeyed, planKeyed } from "../render/keyed.ts";
import type { ComponentInstance } from "../render/component.ts";
import type { ConfirmItem, TaskRow, TaskState } from "../runtime/services/tasks.ts";
import { t } from "./i18n.ts";
import {
  autoRetryKey,
  buildConfirmItems,
  deriveArtifactLinks,
  deriveLiveChips,
  deriveRecoveryActions,
  deriveRoundChips,
  deriveThinkingSummary,
  deriveThoughtRows,
  failureLabelKey,
  isInternalArtifact,
  rejectReasonMissing,
  statusLabel,
  summarizeTask,
  trimKeys,
  type ChatMessage,
  type ThoughtView,
} from "./view-model.ts";
import { ICON_CHEVRON } from "./icons.ts";

/** M7 B3（ST-13）：流卡片渲染上限（旧壳 MAX_CARDS=400 直裁口径）。 */
const MAX_UNIT_CARDS = 400;

/** 终态集合（思维链折叠/恢复动作判定用）。 */
const TERMINAL: readonly string[] = [
  "done", "partial", "failed", "cancelled", "error",
];

export interface StreamProps {
  state: TaskState;
  wsId: string;
  /** 会话聊天记录（修复②，2026-09-20）：历史双侧消息（当前会话） */
  transcript: readonly ChatMessage[];
  onCopyMessage(text: string): void;
  onEditMessage(text: string): void;
  /** G1：从此轮分支（可选——向后兼容） */
  onBranchMessage?(round: number, text: string): void;
  /** 返回 true = 服务端已受理（记入已决反馈）；false/拒绝 = 保留待确认行。 */
  onConfirm(items: readonly ConfirmItem[], reason: string): Promise<boolean>;
  /** E2-5（A10）：答复提问（返回 true = 服务端已受理）；可选——向后兼容 */
  onAnswer?(unitId: string, questionId: string, answer: string,
            source: string): Promise<boolean>;
  onRetry(text: string): void;
  onResume(): void;
  /** 二期批 1：needs_design 跳过设计仍要执行（可选——向后兼容） */
  onOverride?(): void;
  onRollback(deleteArtifacts: boolean): void;
  /** 轮次化（批 3）：并行碎片 chip 点击 → 打开碎片会话（可选——向后兼容） */
  onOpenFragment?(unitId: string): void;
  /** 2026-10-01：历史轮交付物 chip 点击 → 打开产物内容（回看之前的工作成果） */
  onOpenArtifact?(path: string): void;
  /** 历史轮富化（2026-09-21）：会话轮数据（并行碎片 chips + 过程摘要） */
  rounds?: readonly import("./view-model.ts").RoundChipSource[];
  /** E3-1/R5（T5）：隔离 worktree 动作（可选——向后兼容） */
  onWorktreeApply?(runId: string): void;
  onWorktreeDiscard?(runId: string): void;
  /** #2 Phase 1.5：交互偏好（呈现级；缺失=默认行为——向后兼容） */
  prefs?(): Record<string, unknown>;
  onPrefsChange?(patch: Record<string, unknown>): void;
}

interface CardEntry {
  readonly node: HTMLElement;
  readonly text: HTMLElement;
  readonly reason: HTMLInputElement;
  readonly impact: HTMLElement;
  readonly viewHost: HTMLElement;
}

interface ThinkEntry {
  readonly node: HTMLElement;
  readonly summary: HTMLElement;
  readonly body: HTMLElement;
  readonly fold: FoldInstance;
}

/** E2-5（A10）：问题卡条目（输入态跨更新保留——keyed 卡片口径）。 */
interface AnswerEntry {
  readonly node: HTMLElement;
  readonly selections: (string | null)[];
  readonly sources: string[];
  readonly inputs: HTMLInputElement[];
  readonly hint: HTMLElement;
}

export function createStream(
  host: HTMLElement,
  initial: StreamProps,
): ComponentInstance<StreamProps> {
  let props = initial;
  let knownKeys: string[] = [];
  let identity = "";
  let rollbackArm = false;
  let lastRecoverSign = "";
  let lastHistSig = "";
  let lastProcStatus = "";   // 过程组自动开合仅在状态切换时（不覆盖用户手动展开）
  let lastThinkTerminal = false;  // 思维链终态自动折叠仅在切换时（Task 3-2 回归修复）
  let lastLiveText = "";
  const cards = new Map<string, CardEntry>();
  const resolved = new Map<string, { approve: boolean; reason: string }>();
  // E2-5（A10）：问题卡——已答反馈 + keyed 卡片（输入态跨更新保留）
  const answered = new Set<string>();
  const answerCards = new Map<string, AnswerEntry>();
  const expandedUnits = new Set<string>();
  const thinkNodes = new Map<string, ThinkEntry>();

  const meta = h("div", { class: "stream-meta" });
  const chatHost = h("div", { class: "stream-chat", dataset: { st: "chat" } });
  const histHost = h("div", { class: "stream-hist" });
  const rowsHost = h("div", { class: "stream-rows" });
  const chipsHost = h("div", { class: "frag-chip-row", dataset: { st: "chip-row" } });
  const thinkHost = h("div", { class: "round-think" });
  const processSummary = h("button", {
    class: "round-summary", dataset: { st: "process-summary" },
    attrs: { type: "button" },
  });
  const processBody = h("div", { class: "round-process-body" }, chipsHost, thinkHost, rowsHost);
  // Wave-2 T8：details → fold 原语（统一 grid-rows 动画；自动开合门控语义不变）
  const process = createFold({ head: processSummary, body: processBody });
  process.root.classList.add("round-process");
  process.root.dataset.st = "process";
  const liveRound = h("div", { class: "round round-live", dataset: { st: "round-live" } });
  const liveUserHost = h("div", { class: "round-live-user" });
  const tailHost = h("div", { class: "stream-tail" });
  liveRound.append(liveUserHost, process.root);
  chatHost.append(histHost, liveRound, tailHost);
  const noticeHost = h("div", { class: "stream-notices" });
  const confirmTitle = h("div", {
    class: "stream-confirm-title",
    text: t("stream.confirmTitle"),
  });
  const batchInfo = h("span", {
    class: "bb-info",
    dataset: { st: "confirm-batch-info" },
  });
  const batchReason = h("input", {
    class: "pop-input bb-reason",
    dataset: { st: "confirm-batch-reason" },
    attrs: { type: "text", id: "confirm-batch-reason", name: "confirm-batch-reason",
             placeholder: t("stream.batchReason"), "aria-label": t("a11y.batchReason"),
             spellcheck: "false" },
    oninput: () => { batchReason.classList.remove("bad"); },
  }) as HTMLInputElement;
  const batchApprove = h("button", {
    class: "btn small primary",
    dataset: { st: "confirm-batch-approve" },
    attrs: { type: "button" },
    text: t("stream.approveSelected"),
    onclick: () => { runBatch(true); },
  }) as HTMLButtonElement;
  const batchReject = h("button", {
    class: "btn small ghost danger",
    dataset: { st: "confirm-batch-reject" },
    attrs: { type: "button" },
    text: t("stream.rejectSelected"),
    onclick: () => { runBatch(false); },
  }) as HTMLButtonElement;
  const batchBar = h("div", { class: "batch-bar stream-batch" },
    batchInfo, batchReason, batchApprove, batchReject);
  const confirmRowsHost = h("div", { class: "stream-confirm-list" });
  const resolvedHost = h("div", { class: "stream-resolved-list" });
  const confirmHost = h("div", { class: "stream-confirms" },
    confirmTitle, batchBar, confirmRowsHost, resolvedHost);
  // E2-5（A10）：问题卡宿主（待答列表 + 已答反馈）
  const answerTitle = h("div", {
    class: "stream-confirm-title",
    text: t("stream.answerTitle"),
  });
  const answerRowsHost = h("div", { class: "stream-answer-list" });
  const answerResolvedHost = h("div", { class: "stream-resolved-list" });
  const answerHost = h("div", { class: "stream-answers" },
    answerTitle, answerRowsHost, answerResolvedHost);
  // E3-1/R5（T5）：隔离 worktree Review 卡宿主
  const worktreeHost = h("div", { class: "stream-worktrees",
                                   dataset: { st: "worktree-card" } });
  const resultHost = h("div", { class: "stream-result" });
  const root = h("section", { class: "stream" },
    meta,
    h("div", { class: "stream-grid" }, chatHost, noticeHost, confirmHost,
      answerHost, worktreeHost, resultHost));
  host.appendChild(root);

  /** 状态点映射（旧壳 stream-card.js statusDot 同口径）。 */
  function statusDot(status: string | undefined): string {
    if (status === "ok") return "ok";
    if (status === "failed" || status === "rejected") return "bad";
    if (status === "cancelled") return "";
    return "run";
  }

  /** 单元状态文案（UnitStatus 词汇：ok→完成 / confirm→待确认，其余→运行中）。 */
  function unitStatusLabel(status: string | undefined): string {
    if (status === "ok") return t("status.done");
    if (status === "failed") return t("status.failed");
    if (status === "confirm") return t("status.pending");
    if (status === "answer") return t("status.answering");
    return t("status.running");
  }

  /** 碎片卡展开详情（A4(二)：域/状态/进度摘要）。 */
  function detailPanel(row: TaskRow | undefined): HTMLElement {
    return h("div", { class: "frag-detail" },
      h("div", { class: "detail-title", text: t("stream.detailTitle") }),
      h("div", { class: "detail-row" },
        h("span", { class: "detail-key", text: t("stream.detailDomain") }),
        h("span", { text: row?.domainId ?? "" })),
      h("div", { class: "detail-row" },
        h("span", { class: "detail-key", text: t("stream.detailStatus") }),
        h("span", { text: unitStatusLabel(row?.status) })),
      (row?.detail ?? "") === "" ? null
        : h("p", { class: "detail-summary", text: row?.detail ?? "" }));
  }

  /** 卡片摘要文案：detail 优先；S1-C 失败分类/自动恢复痕迹追加；终态无内容用「—」。 */
  function unitStateText(row: TaskRow | undefined): string {
    const status = row?.status ?? "running";
    const base = (row?.detail ?? "") !== ""
      ? row?.detail ?? ""
      : (status === "ok" || status === "failed" ? "—" : t("stream.waiting"));
    const parts: string[] = [];
    const fc = row?.failureClass ?? "";
    if (fc !== "") {
      parts.push(t(failureLabelKey(fc)));
      if (fc === "provider") parts.push(t("failure.retryHint"));
    }
    const kind = row?.autoRetryKind ?? "";
    if (kind !== "") {
      parts.push(t(autoRetryKey(kind), { n: String(row?.autoRetryN ?? 0) }));
    }
    if (parts.length === 0) return base;
    return base === "—" ? parts.join(" · ") : `${base} · ${parts.join(" · ")}`;
  }

  function toggleUnit(key: string): void {
    if (expandedUnits.has(key)) expandedUnits.delete(key);
    else expandedUnits.add(key);
    update(props);
  }

  function checkedIds(): string[] {
    return [...confirmRowsHost.querySelectorAll<HTMLInputElement>("input[type='checkbox']:checked")]
      .map((el) => el.dataset.unit ?? "")
      .filter((unitId) => unitId !== "");
  }

  function refreshBatch(): void {
    const pending = props.state.pendingConfirms.length;
    batchBar.hidden = pending < 2; // 旧壳口径：≥2 挂起才显示批量条
    if (batchBar.hidden) return;
    const checked = checkedIds().length;
    batchInfo.textContent = t("stream.batchInfo", {
      count: String(pending), checked: String(checked),
    });
    batchApprove.textContent = t("stream.approveSelected");
    batchReject.textContent = t("stream.rejectSelected");
    batchApprove.disabled = checked === 0;
    batchReject.disabled = checked === 0;
    batchReason.placeholder = t("stream.batchReason");
  }

  function submit(items: readonly ConfirmItem[], reasonText: string): void {
    props.onConfirm(items, reasonText).then(
      (ok) => {
        if (!ok) return;
        for (const [unitId, approve] of items) {
          resolved.set(unitId, { approve, reason: reasonText });
        }
        batchReason.value = "";
        batchReason.classList.remove("bad");
        update(props);
      },
      () => {
        // 失败经命令总线全局呈现（onCommandFailure 全局面 errorBox）——待确认行保留可重试
      },
    );
  }

  function runBatch(approve: boolean): void {
    const picked = checkedIds();
    if (picked.length === 0) return;
    if (approve) {
      submit(buildConfirmItems(picked, true), "");
      return;
    }
    const reasonText = batchReason.value.trim();
    if (rejectReasonMissing(reasonText)) {
      batchReason.classList.add("bad");
      batchReason.focus();
      return;
    }
    submit(buildConfirmItems(picked, false), reasonText);
  }

  function buildCard(item: ConfirmDto): CardEntry {
    const check = h("input", {
      dataset: { unit: item.unit_id, st: `confirm-check:${item.unit_id}` },
      attrs: { type: "checkbox", title: t("stream.batchCheck"),
               "aria-label": t("stream.batchCheck"),
               id: `confirm-check-${item.unit_id}`, name: "confirm-check" },
      onchange: () => { refreshBatch(); },
    }) as HTMLInputElement;
    const text = h("p", { class: "confirm-reason" });
    const impact = h("div", {
      class: "cf-impact", dataset: { st: `confirm-impact:${item.unit_id}` },
    });
    const viewHost = h("div", {
      class: "cf-view", dataset: { st: `confirm-view:${item.unit_id}` },
    });
    const reason = h("input", {
      class: "pop-input cf-reason",
      dataset: { st: `confirm-reason:${item.unit_id}` },
      attrs: { type: "text", id: `confirm-reason-${item.unit_id}`, name: "confirm-reason",
               placeholder: t("stream.rejectPlaceholder"), "aria-label": t("a11y.rejectReason"),
               spellcheck: "false" },
      oninput: () => { reason.classList.remove("bad"); },
    }) as HTMLInputElement;
    const approve = h("button", {
      class: "btn small primary confirm-approve",
      dataset: { st: `confirm-approve:${item.unit_id}` },
      attrs: { type: "button" },
      onclick: () => { submit([[item.unit_id, true]], ""); },
    }, h("span", { class: "seal-stamp", attrs: { "aria-hidden": "true" }, text: "无形" }),
      t("stream.approve"));
    const reject = h("button", {
      class: "btn small ghost danger",
      dataset: { st: `confirm-reject:${item.unit_id}` },
      attrs: { type: "button" },
      text: t("stream.reject"),
      onclick: () => {
        const reasonText = reason.value.trim();
        if (rejectReasonMissing(reasonText)) {
          reason.classList.add("bad");
          reason.focus();
          return;
        }
        submit([[item.unit_id, false]], reasonText);
      },
    });
    const node = h("section", {
      class: "stream-card confirm-card stream-confirm-row",
      dataset: { unit: item.unit_id, st: `confirm:${item.unit_id}` },
    },
      h("header", { class: "card-head" },
        h("label", { class: "cf-check", attrs: { title: t("stream.batchCheck") } }, check),
        h("span", { class: "dom-tag", text: item.domain_id }),
        h("span", { class: "unit-id", text: item.unit_id }),
        h("span", { class: "card-status" },
          h("i", { class: "dot warn" }), t("stream.needsConfirm")),
        h("span", { class: "card-actions" }, approve, reject)),
      h("div", { class: "card-body" },
        viewHost, text, impact, h("div", { class: "cf-reason-row" }, reason)));
    return { node, text, reason, impact, viewHost };
  }

  /** E2-5（A10）：问题卡（题面 + 选项 + 自由文本；提交后本地反馈+事件流收敛）。 */
  function buildAnswerCard(item: QuestionListDto): AnswerEntry {
    const selections: (string | null)[] = item.questions.map(() => null);
    const sources: string[] = item.questions.map(() => "option");
    const inputs: HTMLInputElement[] = [];
    const hint = h("div", { class: "af-hint bad",
      dataset: { st: `answer-hint:${item.question_id}` } });
    const frame = h("p", {
      class: "af-frame",
      text: item.kind === "browser_access"
        ? t("stream.askMechanism") : t("stream.askUntrusted"),
    });
    const questionNodes = item.questions.map((q, qi) => {
      const optionButtons: HTMLElement[] = [];
      const opts = h("div", { class: "af-options" },
        ...q.options.map((opt, oi) => {
          const btn = h("button", {
            class: "btn small ghost af-option",
            dataset: { st: `answer-option:${item.question_id}:${qi}:${oi}` },
            attrs: { type: "button" },
            text: opt,
            onclick: () => {
              selections[qi] = opt;
              sources[qi] = "option";
              for (const el of optionButtons) el.classList.remove("on");
              btn.classList.add("on");
              const input = inputs[qi];
              if (input !== undefined) input.value = "";
            },
          });
          optionButtons.push(btn);
          return btn;
        }));
      const input = h("input", {
        class: "pop-input af-text",
        dataset: { st: `answer-text:${item.question_id}:${qi}` },
        attrs: { type: "text",
                 placeholder: t("stream.answerPlaceholder"),
                 spellcheck: "false" },
        oninput: () => {
          if (input.value.trim() !== "") {
            selections[qi] = input.value;
            sources[qi] = "text";
            for (const el of optionButtons) el.classList.remove("on");
          }
        },
      }) as HTMLInputElement;
      inputs.push(input);
      return h("div", { class: "af-question" },
        h("p", { class: "af-title", text: q.title }), opts, input);
    });
    const submit = h("button", {
      class: "btn small primary",
      dataset: { st: `answer-submit:${item.question_id}` },
      attrs: { type: "button" },
      text: t("stream.answerSubmit"),
      onclick: () => {
        const parts: string[] = [];
        for (let qi = 0; qi < selections.length; qi++) {
          const val = (selections[qi] ?? "").trim();
          if (val === "") {
            hint.textContent = t("stream.answerHint");
            return;
          }
          parts.push(`Q${qi + 1} ${item.questions[qi]?.title ?? ""}：${val}`);
        }
        hint.textContent = "";
        const source = sources.includes("text") ? "text" : "option";
        void props.onAnswer?.(item.unit_id, item.question_id,
                               parts.join("\n"), source).then(
          (ok) => { if (ok) { answered.add(item.question_id); update(props); } },
          () => { /* 失败经命令总线全局呈现——卡片保留可重试 */ },
        );
      },
    });
    const node = h("section", {
      class: "stream-card confirm-card stream-answer-row",
      dataset: { unit: item.unit_id, st: `answer:${item.question_id}` },
    },
      h("header", { class: "card-head" },
        h("span", { class: "dom-tag", text: item.domain_id }),
        h("span", { class: "unit-id", text: item.unit_id }),
        h("span", { class: "card-status" },
          h("i", { class: "dot warn" }), t("stream.answerNeeded")),
        h("span", { class: "card-actions" }, submit)),
      h("div", { class: "card-body" }, frame, ...questionNodes, hint));
    return { node, selections, sources, inputs, hint };
  }

  /** A′：四要素视图渲染（技术细节折叠；位置/触发为次级行）。 */
  function viewNodes(v: Record<string, string>, item: ConfirmDto): HTMLElement[] {
    const prefs = props.prefs?.() ?? {};
    const concise = prefs["confirm_verbosity"] === "concise";
    const openByDefault = prefs["details_default_open"] === true;
    const remember = prefs["remember_details_choice"] === true;
    const rows: HTMLElement[] = [];
    const line = (cls: string, text: string): HTMLElement =>
      h("p", { class: `cf-view-${cls}`, text });
    if (v.title) rows.push(line("title", v.title));
    if (v.object) rows.push(line("object", v.object));
    if (v.allow_effect) rows.push(line("allow", v.allow_effect));
    if (v.deny_effect) rows.push(line("deny", v.deny_effect));
    if (v.action_hint) rows.push(line("hint", v.action_hint));
    const meta: HTMLElement[] = [];
    if (!concise) {                  // #2 P1.5：简洁档隐藏次级行（四要素永不在简约档隐藏）
      if (v.trigger) meta.push(line("trigger", v.trigger));
      if (v.position) meta.push(line("position", v.position));
    }
    meta.push(h("button", {
      class: "cf-pref-link",
      dataset: { st: `confirm-pref:${item.unit_id}` },
      attrs: { type: "button" },
      text: concise ? t("stream.prefVerbose") : t("stream.prefConcise"),
      onClick: () => {
        props.onPrefsChange?.({
          confirm_verbosity: concise ? "standard" : "concise",
        });
      },
    }));
    if (meta.length > 0) rows.push(h("div", { class: "cf-view-meta" }, ...meta));
    const details = impactNodes(item.impact);
    if (details.length > 0) {
      rows.push(h("details", {
        class: "cf-details",
        dataset: { st: `confirm-details:${item.unit_id}` },
        ...(openByDefault ? { attrs: { open: "open" } } : {}),
        onToggle: (ev: Event) => {   // 记住选择：写回用户级默认（可选，失败回退）
          if (remember && props.onPrefsChange) {
            props.onPrefsChange({
              details_default_open: (ev.target as HTMLDetailsElement).open,
            });
          }
        },
      }, h("summary", { text: t("stream.viewDetails") }), ...details));
    }
    return rows;
  }

  /** 影响清单（M7 #7 · A2）：碎片摘要/工具/依赖/交付——无数据不渲染。 */
  function impactNodes(impact: Record<string, unknown>): HTMLElement[] {
    const list = (v: unknown): string[] => Array.isArray(v) ? v.map(String) : [];
    const tools = list(impact.tools);
    const depends = list(impact.depends);
    const deliverables = list(impact.deliverables);
    const summary = typeof impact.summary === "string" ? impact.summary : "";
    const rows: HTMLElement[] = [];
    const row = (key: string, val: string): HTMLElement =>
      h("div", { class: "cf-impact-row" },
        h("span", { class: "cf-impact-key", text: key }),
        h("span", { class: "cf-impact-val", text: val }));
    if (summary !== "") rows.push(row(t("stream.impactSummary"), summary));
    if (tools.length > 0) rows.push(row(t("stream.impactTools"), tools.join(" · ")));
    if (depends.length > 0) rows.push(row(t("stream.impactDepends"), depends.join(" · ")));
    if (deliverables.length > 0) rows.push(row(t("stream.impactDeliverables"), deliverables.join(" · ")));
    return rows;
  }

  /** 时间锚点（epoch 秒 → HH:MM；缺省/非法 → 空串不渲染）。 */
  function fmtClock(ts?: number): string {
    if (typeof ts !== "number" || !Number.isFinite(ts) || ts <= 0) return "";
    const d = new Date(ts * 1000);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  /** 用户消息气泡（修复②）：右侧 + 复制/编辑操作（G1：历史轮可分支）。 */
  function userBubble(text: string, live: boolean, round = 0, ts?: number): HTMLElement {
    const branchBtn = !live && round > 0 && props.onBranchMessage !== undefined
      ? h("button", {
          class: "chat-act",
          attrs: { type: "button", "data-st": "chat-branch" },
          text: t("chat.branch"),
          onClick: () => { props.onBranchMessage?.(round, text); },
        })
      : null;
    const clock = fmtClock(ts);
    const cell = h("div", { class: "chat-msg chat-user" },
      h("div", { class: "chat-bubble" },
        h("div", { class: "chat-text", text }),
        clock !== ""
          ? h("div", { class: "chat-time", attrs: { "data-st": "chat-time" }, text: clock })
          : null),
      h("div", { class: "chat-actions" },
        h("button", {
          class: "chat-act", attrs: { type: "button", "data-st": "chat-copy" },
          text: t("chat.copy"),
          onClick: () => { props.onCopyMessage(text); },
        }),
        h("button", {
          class: "chat-act", attrs: { type: "button", "data-st": "chat-edit" },
          text: t("chat.edit"),
          onClick: () => { props.onEditMessage(text); },
        }),
        branchBtn));
    if (live) cell.dataset.st = "chat-live-user";
    return cell;
  }

  /** 实时轮用户泡（持久节点——文本变化时重建内容；过程组宿主不重建）。 */
  function renderLiveUser(text: string): void {
    liveUserHost.replaceChildren(userBubble(text, true));
  }

  /** 助手消息气泡（修复②）：左侧 + 交付物 chips（2026-10-01：chips 可点击回看）。 */
  function assistantBubble(msg: ChatMessage): HTMLElement {
    const clock = fmtClock(msg.ts);
    return h("div", { class: "chat-msg chat-assistant", dataset: { st: "chat-assistant" } },
      h("div", { class: "chat-bubble" },
        h("div", { class: "chat-text", text: msg.text }),
        msg.artifacts.length > 0
          ? h("div", { class: "chat-refs" },
              ...msg.artifacts.filter((p) => !isInternalArtifact(p)).slice(0, 5).map((p) =>
                props.onOpenArtifact !== undefined
                  ? h("button", {
                      class: "chat-ref chat-ref-btn",
                      attrs: { type: "button", title: p },
                      text: p,
                      onClick: () => { props.onOpenArtifact?.(p); },
                    })
                  : h("span", { class: "chat-ref", text: p })))
          : null,
        clock !== ""
          ? h("div", { class: "chat-time", attrs: { "data-st": "chat-time" }, text: clock })
          : null));
  }

  /** 报告折叠（Wave-2 T8：details → fold；标题/文本不变）。 */
  function reportFoldNode(report: string): HTMLElement {
    const head = h("button", {
      class: "fold-block-head", attrs: { type: "button" },
      text: t("stream.reportTitle"),
    });
    const fold = createFold({
      head, body: h("pre", { class: "stream-report", text: report }),
    });
    fold.root.classList.add("fold-block");
    fold.root.dataset.st = "report-fold";
    return fold.root;
  }

  /** 思维链块（Task 3-2）：keyed 增量更新——文本仅在变化时写（textContent 级）；
   *  不重建 details 元素（保留用户展开/折叠与滚动）；新建时按运行态默认开合。 */
  function renderThoughts(thoughts: readonly ThoughtView[]): void {
    const desired: HTMLElement[] = [];
    const seen = new Set<string>();
    for (const thought of thoughts) {
      const key = `${thought.unitId}|${thought.round}`;
      seen.add(key);
      let entry = thinkNodes.get(key);
      if (entry === undefined) {
        const body = h("div", { class: "think-body", text: thought.text });
        const summary = h("button", {
          class: "think-head",
          attrs: { type: "button",
                   title: `${thought.unitId} · ${t("stream.round", { n: String(thought.round) })}` },
          text: deriveThinkingSummary([thought], thought.open)
            ?? `${t("stream.thinking")} · ${thought.unitId}`,
        });
        // Wave-2 T8：details → fold（终态自动折叠一次、用户手动开合不覆盖——门控不变）
        const fold = createFold({ head: summary, body, open: thought.open });
        fold.root.classList.add("think-block");
        fold.root.dataset.st = `think:${thought.unitId}`;
        entry = { node: fold.root, summary, body, fold };
        thinkNodes.set(key, entry);
      }
      if (entry.body.textContent !== thought.text) entry.body.textContent = thought.text;
      const label = deriveThinkingSummary([thought], thought.open)
        ?? `${t("stream.thinking")} · ${thought.unitId}`;
      if (entry.summary.textContent !== label) entry.summary.textContent = label;
      desired.push(entry.node);
    }
    // 按需重排（位置已对不改 DOM——不重排不丢焦点/滚动）
    for (let i = 0; i < desired.length; i += 1) {
      const node = desired[i];
      if (node !== undefined && thinkHost.children[i] !== node) {
        thinkHost.insertBefore(node, thinkHost.children[i] ?? null);
      }
    }
    // 已裁剪（上下文上限）的旧块移除
    for (const [key, entry] of [...thinkNodes]) {
      if (!seen.has(key)) {
        entry.node.remove();
        thinkNodes.delete(key);
      }
    }
  }

  const update = (next: StreamProps): void => {
    props = next;
    const state = next.state;
    const recoverSign = `${state.runId}|${state.status}`;
    if (recoverSign !== lastRecoverSign) {
      lastRecoverSign = recoverSign;
      rollbackArm = false;
    }
    meta.textContent = [state.taskText, summarizeTask(state)]
      .filter((part) => part !== "")
      .join(" · ");

    // 会话聊天（轮次化 2026-09-21）：历史消息（签名门控）+ 实时轮（持久节点——keyed 过程组宿主）
    const transcript = props.transcript;
    const lastUser = [...transcript].reverse().find((m) => m.kind === "user");
    const showLive = state.taskText !== "" && state.status !== "idle"
      && (!lastUser || lastUser.text !== state.taskText);
    const histSig = transcript.map((m) => `${m.kind}:${m.round}:${m.text}`).join("\u0001")
      + "|" + (props.rounds ?? [])
        .map((r) => `${r.round}:${r.fragments.filter((f) => f.parallel).length}`).join(",");
    if (histSig !== lastHistSig) {
      lastHistSig = histSig;
      // 完成态：当前轮用户消息与答复之间插入过程组（轮次化结构 user → process → answer）
      let split = -1;
      if (!showLive && lastUser && lastUser.text === state.taskText) {
        for (let i = transcript.length - 1; i >= 0; i -= 1) {
          if (transcript[i]?.kind === "user") { split = i; break; }
        }
      }
      const prefix = split >= 0 ? transcript.slice(0, split + 1) : transcript;
      const tail = split >= 0 ? transcript.slice(split + 1) : [];
      // 历史轮富化：用户消息后插入「过程摘要 + 并行碎片 chips」（线性轮无富化）
      const roundNodes = (msgs: readonly ChatMessage[]): HTMLElement[] => {
        const nodes: HTMLElement[] = [];
        for (const m of msgs) {
          nodes.push(m.kind === "user" ? userBubble(m.text, false, m.round, m.ts) : assistantBubble(m));
          if (m.kind !== "user") continue;
          const e = deriveRoundChips(props.rounds ?? [], m.round);
          if (e === null) continue;
          nodes.push(h("div", { class: "round-enrich", dataset: { st: "round-enrich" } },
            h("div", { class: "round-note", text: e.summary }),
            h("div", { class: "frag-chip-row" }, ...e.chips.map((chip) => h("span", {
              class: "frag-chip", dataset: { st: `frag-chip:${chip.unitId}` },
              attrs: { title: `${chip.domain} · ${chip.label}` },
              onClick: () => { props.onOpenFragment?.(chip.unitId); },
            },
              h("span", { class: "dom-tag", text: chip.domain }),
              h("span", { text: chip.label }))))));
        }
        return nodes;
      };
      histHost.replaceChildren(...roundNodes(prefix));
      tailHost.replaceChildren(...roundNodes(tail));
    }
    // 实时轮可见性：运行中显示用户泡；完成态保留过程组（不重复用户消息——已入历史）
    const liveVisible = showLive || (state.rows.length > 0 && state.status !== "idle");
    liveRound.hidden = !liveVisible;
    liveUserHost.hidden = !showLive;
    if (showLive && state.taskText !== lastLiveText) {
      lastLiveText = state.taskText;
      liveUserHost.replaceChildren(userBubble(state.taskText, true));
    }
    chatHost.hidden = histHost.childElementCount === 0 && !liveVisible;

    // 单元行：keyed（已存在行仅更新类名/域/详情——不重建）
    const keys = state.rows.map((row) => row.unitId);
    const plan = planKeyed(knownKeys, keys);
    knownKeys = keys;
    const byKey = new Map(state.rows.map((row) => [row.unitId, row]));
    applyKeyed(
      rowsHost,
      plan,
      (key) => {
        const row = byKey.get(key);
        return h("section", {
          class: `unit-card${expandedUnits.has(key) ? " expanded" : ""}`,
          dataset: { unit: key, status: row?.status ?? "running", st: `unit:${key}` },
          attrs: { tabindex: "0", role: "button", title: t("stream.expandTitle") },
          onClick: () => { toggleUnit(key); },
        },
          h("header", { class: "frag-head" },
            h("span", { class: "dom-tag", text: row?.domainId ?? "" }),
            h("span", { class: "unit-id", text: key }),
            h("span", { class: "frag-status card-status" },
              h("i", { class: `dot ${statusDot(row?.status)}` }),
              unitStatusLabel(row?.status)),
            h("span", { class: "expand-chev" }, svgIcon(ICON_CHEVRON))),
          h("div", { class: "frag-swap" },
            h("div", { class: "frag-body" },
              h("div", { class: "frag-state", text: unitStateText(row) }),
              h("div", { class: "frag-meta" })),
            detailPanel(row)));
      },
      (key, node) => {
        const row = byKey.get(key);
        node.classList.toggle("expanded", expandedUnits.has(key));
        node.dataset.status = row?.status ?? "running";
        const status = node.querySelector<HTMLElement>(".frag-status");
        if (status) {
          status.replaceChildren(
            h("i", { class: `dot ${statusDot(row?.status)}` }),
            unitStatusLabel(row?.status));
        }
        const state = node.querySelector<HTMLElement>(".frag-state");
        if (state) state.textContent = unitStateText(row);
        const domain = node.querySelector<HTMLElement>(".dom-tag");
        if (domain) domain.textContent = row?.domainId ?? "";
        if (expandedUnits.has(key)) {
          const detail = node.querySelector<HTMLElement>(".frag-detail");
          if (detail) detail.replaceChildren(...Array.from(detailPanel(row).childNodes));
        }
      },
    );

    // 流上限裁剪（M7 B3 · ST-13）：裁最旧卡 + 同步 keyed 状态（防 DOM 与 knownKeys 漂移）
    const keptKeys = trimKeys(knownKeys, MAX_UNIT_CARDS);
    if (keptKeys.length < knownKeys.length) {
      const drop = knownKeys.length - keptKeys.length;
      for (let i = 0; i < drop && rowsHost.firstChild; i += 1) {
        rowsHost.removeChild(rowsHost.firstChild);
      }
      knownKeys = [...rowsHost.children]
        .map((el) => (el as HTMLElement).dataset.unit ?? "")
        .filter((key) => key !== "");
    }

    // 过程组（轮次化）：运行中展开实时；完成态默认收起为摘要行（内容仍在 DOM——可手动展开）
    const terminal = TERMINAL.includes(state.status);
    const running = state.status !== "idle" && !terminal;
    // 自动开合仅在状态切换时生效（2026-09-22 修复）：终态后续任何渲染不得把
    // 用户手动展开的过程组再次收起（原每次 update 强制 open=running）
    if (state.status !== lastProcStatus) {
      lastProcStatus = state.status;
      process.setOpen(running);
    }
    const steps = state.rows.length;
    // Task A3（Wave-1）：回复消息直显（pi 式）——过程摘要恢复纯步数文案
    processSummary.textContent = running
      ? t("stream.processRunning", { steps: String(steps) })
      : t("stream.processSummary", { steps: String(steps) });
    const chips = deriveLiveChips(state.rows);
    chipsHost.hidden = chips.length === 0;
    chipsHost.replaceChildren(...chips.map((chip) => h("span", {
      class: "frag-chip", dataset: { st: `frag-chip:${chip.unitId}` },
      attrs: { title: `${chip.domain} · ${chip.label}` },
      onClick: () => { props.onOpenFragment?.(chip.unitId); },
    },
      h("span", { class: "dom-tag", text: chip.domain }),
      h("span", { text: chip.label }))));
    // Task 3-2 回归修复（E2E next_slice）：终态切换时思维链块自动折叠一次
    // （既有行为保留；keyed 渲染此后不再覆盖用户手动开合）
    if (terminal && !lastThinkTerminal) {
      for (const entry of thinkNodes.values()) entry.fold.setOpen(false);
    }
    lastThinkTerminal = terminal;
    renderThoughts(deriveThoughtRows(state.thoughts, terminal));

    // 安全拦截卡 + FSC 提示行（A10：SafetyBlocked / FscAudit / FscSwitch 流内呈现）
    noticeHost.replaceChildren(
      ...state.safety.map((s) => h("section", {
        class: "stream-card safety-card",
        dataset: { st: `safety:${s.seq}` },
      },
        h("header", { class: "card-head" },
          h("span", { class: "dom-tag warn-tag", text: t("stream.safetyTitle") }),
          h("span", { class: "unit-id", text: s.unitId })),
        h("div", { class: "card-body" },
          h("p", { class: "sf-reason", text: s.reason || t("stream.safetyReason") }),
          h("code", { class: "sf-cmd", text: s.command === "" ? s.tool : `${s.tool} · ${s.command}` })))),
      ...state.fsc.map((f) => h("div", {
        class: "notice-row",
        dataset: { st: `fsc:${f.kind}:${f.seq}` },
        text: f.kind === "audit"
          ? t("stream.fscAudit", { ratio: `${Math.round(f.ratio * 100)}%` })
          : t("stream.fscSwitch", { ratio: `${Math.round(f.ratio * 100)}%` }),
      })));

    // 确认门：keyed 卡片（输入态跨更新保留）+ 已决反馈（会话内）
    const identityNext = `${state.runId}|${state.taskText}`;
    if (identityNext !== identity) {
      identity = identityNext;
      resolved.clear();
      answered.clear();
      expandedUnits.clear();
    }
    const pendingIds = new Set(state.pendingConfirms.map((item) => item.unit_id));
    for (const unitId of pendingIds) resolved.delete(unitId); // 再次挂起 → 回到待确认
    for (const [unitId, entry] of [...cards]) {
      if (pendingIds.has(unitId)) continue;
      entry.node.remove();
      cards.delete(unitId);
    }
    for (const item of state.pendingConfirms) {
      let entry = cards.get(item.unit_id);
      if (!entry) {
        entry = buildCard(item);
        cards.set(item.unit_id, entry);
        confirmRowsHost.append(entry.node);
      }
      const v = ((item as { view?: Record<string, unknown> }).view ?? {}) as Record<string, unknown>;
      const vs: Record<string, string> = {};
      for (const [k, val] of Object.entries(v)) {
        if (typeof val === "string") vs[k] = val;
      }
      if ((vs.title ?? "") !== "") {
        entry.viewHost.hidden = false;
        entry.viewHost.replaceChildren(...viewNodes(vs, item));
        entry.text.hidden = true;
        entry.impact.hidden = true;
      } else {                       // 兼容回退：旧事件无 view → reason + impact
        entry.viewHost.hidden = true;
        entry.text.hidden = false;
        entry.impact.hidden = false;
        entry.text.textContent = item.reason || t("stream.confirmReason");
        entry.impact.replaceChildren(...impactNodes(item.impact));
      }
      entry.reason.placeholder = t("stream.rejectPlaceholder");
    }
    confirmTitle.textContent = t("stream.confirmTitle");
    confirmTitle.hidden = state.pendingConfirms.length === 0;
    resolvedHost.replaceChildren(...[...resolved].map(([unitId, entry]) =>
      h("div", {
        class: "cf-resolved",
        dataset: { st: `confirm-resolved:${unitId}` },
        text: `${entry.approve ? t("stream.approved") : t("stream.rejected")}` +
          `${entry.reason ? ` · ${entry.reason}` : ""}`,
      })));
    confirmHost.hidden = state.pendingConfirms.length === 0 && resolved.size === 0;
    refreshBatch();

    // 问题卡（A10）：keyed 卡片（输入态跨更新保留）+ 已答反馈
    const pendingQids = new Set(
      state.pendingAnswers.map((item) => item.question_id));
    for (const [qid, entry] of [...answerCards]) {
      if (pendingQids.has(qid)) continue;
      entry.node.remove();
      answerCards.delete(qid);
    }
    for (const item of state.pendingAnswers) {
      if (answerCards.has(item.question_id)) continue;
      const entry = buildAnswerCard(item);
      answerCards.set(item.question_id, entry);
      answerRowsHost.append(entry.node);
    }
    answerTitle.textContent = t("stream.answerTitle");
    answerTitle.hidden = state.pendingAnswers.length === 0;
    answerResolvedHost.replaceChildren(...[...answered].map((qid) =>
      h("div", {
        class: "cf-resolved",
        dataset: { st: `answer-resolved:${qid}` },
        text: t("stream.answerResolved"),
      })));
    answerHost.hidden = state.pendingAnswers.length === 0 && answered.size === 0;

    // E3-1/R5（T5）：隔离 worktree Review 卡（Ready → 变更清单/diff/动作）
    const wt = state.worktree;
    worktreeHost.hidden = wt === null;
    if (wt !== null) {
      const noticeText = wt.notice === null ? ""
        : wt.notice.kind === "applied"
          ? t("worktree.applied", { n: String(wt.notice.n ?? 0) })
          : wt.notice.kind === "review_failed"
            ? t("worktree.reviewFailed", { msg: wt.notice.msg ?? "" })
            : wt.notice.kind === "discard_failed"
              ? t("worktree.discardFailed", { msg: wt.notice.msg ?? "" })
              : t("worktree.applyFailed", { msg: wt.notice.msg ?? "" });
      const fileNodes = wt.files.length === 0
        ? [h("div", { class: "wt-empty", text: t("worktree.noChanges") })]
        : wt.files.map((f) => h("div", {
            class: "wt-file",
            attrs: { "data-st": `worktree-file:${f.path}` },
            text: `${f.status}  ${f.path}`,
          }));
      const applyBtn = h("button", {
        class: "btn small primary",
        attrs: { type: "button", "data-st": "worktree-apply" },
        text: t("worktree.apply"),
        onClick: () => { props.onWorktreeApply?.(wt.runId); },
      }) as HTMLButtonElement;
      applyBtn.disabled = wt.busy;
      const discardBtn = h("button", {
        class: "btn small ghost danger",
        attrs: { type: "button", "data-st": "worktree-discard" },
        text: t("worktree.discard"),
        onClick: () => {
          if (window.confirm(t("worktree.discardConfirm"))) {
            props.onWorktreeDiscard?.(wt.runId);
          }
        },
      }) as HTMLButtonElement;
      discardBtn.disabled = wt.busy;
      worktreeHost.replaceChildren(
        h("div", { class: "stream-confirm-title", text: t("worktree.title") }),
        h("div", { class: "wt-path",
                    attrs: { "data-st": "worktree-path" }, text: wt.path }),
        ...fileNodes,
        ...(wt.diff === "" ? [] : [
          h("div", { class: "stream-confirm-title", text: t("worktree.diff") }),
          h("pre", { class: "wt-diff",
                      attrs: { "data-st": "worktree-diff" }, text: wt.diff }),
        ]),
        h("div", { class: "wt-actions" }, applyBtn, discardBtn),
        ...(noticeText === "" ? [] : [h("div", {
          class: "wt-notice",
          attrs: { "data-st": "worktree-notice" }, text: noticeText,
        })]),
      );
    }

    // 结果 / 错误（P2-M6：产物链接 + 恢复动作；思维链已移入过程组——轮次化 2026-09-21）
    resultHost.replaceChildren();
    if (state.result) {
      const links = deriveArtifactLinks(state.result, state.unitArtifacts, props.wsId);
      const body: (HTMLElement | null)[] = [
        h("div", { class: "result-line" },
          h("span", { class: "rl-main", text: `结果：${statusLabel(state.status)}` }),
          h("span", { class: "rl-meta" },
            state.runId === "" ? null : `run ${state.runId.slice(0, 8)} · `,
            h("span", {
              attrs: { "data-st": "result-artifacts-count",
                       title: t("stream.artifactsOwnership") },
              text: t("stream.artifactsCount", { n: String(links.length) }),
            }))),
        reportFoldNode(state.result.report),
      ];
      if (links.length > 0) {
        body.push(h("div", { class: "stream-artifacts" },
          ...links.map((link) => h("a", {
            class: "artifact-tile",
            attrs: {
              href: link.url, target: "_blank", rel: "noopener",
              "data-st": `artifact:${link.path}`,
            },
          },
            h("span", { class: "path", text: link.path }),
            link.kind === "" ? null : h("span", { class: "kind", text: link.kind })))));
      }
      resultHost.append(h("section", { class: "stream-card result-card" },
        h("header", { class: "card-head" },
          h("span", { class: "dom-tag", text: t("stream.resultTitle") }),
          state.runId === "" ? null
            : h("span", { class: "card-hint", text: `run ${state.runId.slice(0, 8)}` })),
        h("div", { class: "card-body" }, ...body)));
    } else if (state.error !== "") {
      resultHost.append(h("section", { class: "stream-card error-card" },
        h("div", { class: "card-body" }, h("p", { text: state.error }))));
    }
    // 恢复动作：在 result/error 之后统一渲染（error/cancelled 无 result 也可见）
    const actions = deriveRecoveryActions(state.status);
    if (actions.length > 0) {
      const nodes: HTMLElement[] = [];
      for (const action of actions) {
        if (action.id === "rollback") {
          if (rollbackArm) {
            nodes.push(
              h("button", {
                class: "btn danger", attrs: { type: "button", "data-st": "recover:rollback-keep" },
                text: t("stream.rollbackKeep"),
                onClick: () => { rollbackArm = false; props.onRollback(false); },
              }),
              h("button", {
                class: "btn danger", attrs: { type: "button", "data-st": "recover:rollback-del" },
                text: t("stream.rollbackDel"),
                onClick: () => { rollbackArm = false; props.onRollback(true); },
              }),
              h("button", {
                class: "btn ghost", attrs: { type: "button", "data-st": "recover:rollback-cancel" },
                text: t("stream.cancel"),
                onClick: () => { rollbackArm = false; update(props); },
              }));
          } else {
            nodes.push(h("button", {
              class: "btn ghost", attrs: { type: "button", "data-st": "recover:rollback" },
              text: t(action.key),
              onClick: () => { rollbackArm = true; update(props); },
            }));
          }
          continue;
        }
        if (action.id === "override") {
          nodes.push(h("button", {
            class: "btn ghost", attrs: { type: "button", "data-st": "recover:override" },
            text: t(action.key),
            onClick: () => { props.onOverride?.(); },
          }));
          continue;
        }
        nodes.push(h("button", {
          class: "btn ghost", attrs: { type: "button", "data-st": `recover:${action.id}` },
          text: t(action.key),
          onClick: () => {
            if (action.id === "retry") props.onRetry(state.taskText);
            else props.onResume();
          },
        }));
      }
      resultHost.append(h("div", { class: "stream-recover" }, ...nodes));
    }
    // 单滚动列：贴近底部才跟随（避免打断向上阅读）
    const scroller = chatHost.closest(".app-stream-slot") as HTMLElement | null;
    if (scroller
        && scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  };
  update(initial);

  return {
    update,
    dispose(): void {
      root.remove();
    },
  };
}
