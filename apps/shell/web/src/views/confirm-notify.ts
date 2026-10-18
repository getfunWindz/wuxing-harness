/** T-2 挂起通知：确认门等待、窗口不可见时的系统通知（Web Notification API——浏览器/Electron 同通道）。
    触发（仅隐藏态）：a) 新出现未通知过的挂起；b) 可见→隐藏切换时已有未通知挂起。
    去重：按 unit id 一次；解决后移出账本（同 id 再现可再通知）。
    值纪律：通知正文仅用既有用户可见文案（截断），不带工具参数/路径。
    v0 不做：通知内决议 / 重复提醒 / 声音 / 窗口关闭后推送（见设计 §3.3）。 */
import { t } from "./i18n.ts";

/** 待确认卡（id + 用户可见标签）。 */
export interface NotifyCard {
  readonly id: string;
  readonly label: string;
}

export interface NotifyDecisionInput {
  readonly cards: readonly NotifyCard[];
  readonly notified: ReadonlySet<string>;
  readonly hidden: boolean;
  readonly enabled: boolean;
  readonly permission: string;   // granted | denied | default | unsupported
}

/** 纯函数：本次应通知的卡（守卫全过 + 未通知过；空数组=不发）。 */
export function notifyCandidates(input: NotifyDecisionInput): NotifyCard[] {
  if (!input.enabled || !input.hidden || input.permission !== "granted") return [];
  return input.cards.filter((card) => !input.notified.has(card.id));
}

const MAX_BODY = 80;

/** 正文：单条=标签（≤80 字符截断）；多条=首条 + 「等 N 个」。 */
export function notifyBody(cards: readonly NotifyCard[]): string {
  const first = (cards[0]?.label ?? "").trim();
  const clip = first.length > MAX_BODY ? `${first.slice(0, MAX_BODY - 1)}…` : first;
  if (cards.length <= 1) return clip;
  return t("notify.more", { first: clip, count: String(cards.length - 1) });
}

/** 环境权限态（无 Notification API → unsupported）。 */
export function permissionState(): string {
  return typeof Notification === "undefined" ? "unsupported" : Notification.permission;
}

export interface ConfirmNotifyDeps {
  /** 当前待确认卡（每次求值）。 */
  cards(): readonly NotifyCard[];
  /** 偏好开关（interaction_prefs.confirm_notify）。 */
  enabled(): boolean;
  /** 权限态（缺省=真实环境）。 */
  permission?(): string;
  /** 是否隐藏（缺省=document.visibilityState）。 */
  isHidden?(): boolean;
  /** 投递（缺省=真实 Notification + 点击聚焦；测试注入）。 */
  create?(title: string, body: string): void;
}

export interface ConfirmNotifier {
  /** 任务状态/偏好变化后调用：剪枝账本 +（满足条件时）通知。 */
  sync(): void;
}

export function createConfirmNotify(deps: ConfirmNotifyDeps): ConfirmNotifier {
  const notified = new Set<string>();
  const isHidden = (): boolean =>
    deps.isHidden?.() ??
    (typeof document !== "undefined" && document.visibilityState !== "visible");
  const emit = (title: string, body: string): void => {
    if (deps.create !== undefined) {
      deps.create(title, body);
      return;
    }
    const notification = new Notification(title, { body });
    notification.onclick = () => { window.focus(); };
  };
  const decide = (): void => {
    const cards = deps.cards();
    const ids = new Set(cards.map((card) => card.id));
    for (const id of [...notified]) {
      if (!ids.has(id)) notified.delete(id);   // 解决/离场 → 剪枝
    }
    const todo = notifyCandidates({
      cards, notified, hidden: isHidden(), enabled: deps.enabled(),
      permission: deps.permission?.() ?? permissionState(),
    });
    if (todo.length === 0) return;
    for (const card of todo) notified.add(card.id);
    emit(t("notify.confirmTitle", { count: String(todo.length) }), notifyBody(todo));
  };
  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", () => { decide(); });
  }
  return { sync: decide };
}
