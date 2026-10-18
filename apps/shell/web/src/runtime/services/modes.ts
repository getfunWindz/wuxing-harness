/** 会话模式服务（双模式批 1）：会话级模式读取/写入。
 *
 * 依据：`docs/WUXING_双模式设计_2026-09-23.md` §3/§7 + 批 1 计划 Task 6。
 * 纪律：读取为后台只读刷新（直连 REST——不进命令总线，防吞用户提交）；
 * 写入为用户动作（走命令总线——失败全局可见）。服务端机制守卫：
 * 非空白会话 PUT → 422 `session/not-blank`（壳侧提示不替代守卫）。 */
import type { SessionModeDto } from "../../protocol/generated.ts";
import type { CommandBus } from "../commands.ts";
import type { WritableRestClient } from "../connection/rest.ts";

export interface ModeSelection {
  readonly mode: string;
  readonly variant: string;
}

/** 选择器条目 id → {mode, variant}（theroad 无变体；旧值 wayfinder 兼容读）。 */
export function splitModeId(id: string): ModeSelection {
  if (id === "theroad" || id === "wayfinder") return { mode: "theroad", variant: "" };
  const idx = id.lastIndexOf("-");
  if (idx <= 0) return { mode: id, variant: "" };
  return { mode: id.slice(0, idx), variant: id.slice(idx + 1) };
}

/** {mode, variant} → 选择器条目 id（用于当前态比较与标签）。 */
export function joinModeId(mode: string, variant: string): string {
  if (mode === "theroad" || mode === "wayfinder") return "theroad";
  return `${mode}-${variant}`;
}

/** 三项选择器条目（顺序即呈现顺序）。 */
export const MODE_IDS: readonly string[] = [
  "minimal-pure",
  "minimal-standard",
  "theroad",
];

export interface ModesService {
  get(wsId: string, session: string): Promise<SessionModeDto>;
  set(wsId: string, session: string, selection: ModeSelection): Promise<SessionModeDto>;
}

export function createModesService(deps: {
  rest: WritableRestClient;
  commands: CommandBus;
}): ModesService {
  const url = (wsId: string, session: string): string =>
    `/api/v1/workspaces/${wsId}/session-modes?session=${encodeURIComponent(session)}`;
  return {
    // 读取：后台只读刷新（直连——同 context.preview 口径）
    get: (wsId, session) => deps.rest.get<SessionModeDto>(url(wsId, session)),
    // 写入：用户动作（走总线；422/网络失败全局可见）
    set: (wsId, session, selection) =>
      deps.commands.run("modes.set", () =>
        deps.rest.put<SessionModeDto>(url(wsId, session), { ...selection })),
  };
}
