/** 会话服务（P2-M2）：列表 / 重命名 / 导出（只读 + 单写操作）。 */
import type { ConversationBranchResultDto, SessionListDto, SessionRoundsDto, SessionTitleDto, UnitSessionDto } from "../../protocol/generated.ts";
import type { CommandBus } from "../commands.ts";
import type { WritableRestClient } from "../connection/rest.ts";

export interface SessionsService {
  list(wsId: string): Promise<SessionListDto>;
  rename(wsId: string, name: string, newName: string): Promise<void>;
  archive(wsId: string, name: string): Promise<void>;
  delete(wsId: string, name: string): Promise<void>;
  /** 修复②：会话消息行（聊天记录——GET /sessions/{name} 的 rows） */
  messages(wsId: string, name: string): Promise<{ name: string; rows: readonly Record<string, unknown>[] }>;
  /** 轮次化（2026-09-21）：会话轮 + 每轮碎片（只读聚合端点——左栏树/历史富化数据源） */
  rounds(wsId: string, name: string): Promise<SessionRoundsDto>;
  /** 碎片会话内容（批 3：碎片=独立会话——会话视图数据源） */
  unitSession(wsId: string, unit: string): Promise<UnitSessionDto>;
  title(wsId: string, name: string): Promise<SessionTitleDto>;
  /** G1：从既有会话轮派生新会话（fork 式——承接摘要 + 血缘） */
  branch(
    wsId: string,
    name: string,
    req: {
      readonly fromRound: number;
      readonly mode: "redo" | "continue";
      readonly summary: "mech" | "llm" | "none";
      readonly focus: string;
    },
  ): Promise<ConversationBranchResultDto>;
  exportUrl(wsId: string, name: string, format?: string): string;
}

export function createSessionsService(deps: {
  rest: WritableRestClient;
  commands: CommandBus;
}): SessionsService {
  const at = (wsId: string, name: string): string =>
    `/api/v1/workspaces/${wsId}/sessions/${encodeURIComponent(name)}`;
  return {
    list: (wsId) =>
      deps.commands.run("sessions.list", () =>
        deps.rest.get<SessionListDto>(`/api/v1/workspaces/${wsId}/sessions`)),
    rename: async (wsId, name, newName) => {
      await deps.commands.run("sessions.rename", () =>
        deps.rest.put(at(wsId, name), { name: newName }));
    },
    archive: async (wsId, name) => {
      await deps.commands.run("sessions.archive", () =>
        deps.rest.post(`${at(wsId, name)}/archive`, {}));
    },
    delete: async (wsId, name) => {
      await deps.commands.run("sessions.delete", () =>
        deps.rest.post(`${at(wsId, name)}/archive`, { state: "trashed" }));
    },
    messages: (wsId, name) =>
      deps.commands.run("sessions.messages", () =>
        deps.rest.get<{ name: string; rows: readonly Record<string, unknown>[] }>(
          at(wsId, name))),
    rounds: (wsId, name) =>
      deps.commands.run("sessions.rounds", () =>
        deps.rest.get<SessionRoundsDto>(`${at(wsId, name)}/rounds`)),
    unitSession: (wsId, unit) =>
      deps.commands.run("sessions.unitSession", () =>
        deps.rest.get<UnitSessionDto>(
          `/api/v1/workspaces/${wsId}/unit-sessions/${encodeURIComponent(unit)}`)),
    title: (wsId, name) =>
      // 后台懒惰取（失败静默——不进命令总线，避免无凭据时逐条报错）
      deps.rest.post<SessionTitleDto>(`${at(wsId, name)}/title`, {}),
    branch: (wsId, name, req) =>
      deps.commands.run("sessions.branch", () =>
        deps.rest.post<ConversationBranchResultDto>(
          `/api/v1/workspaces/${wsId}/conversations/branch`,
          { session: name, from_round: req.fromRound, mode: req.mode,
            summary: req.summary, focus: req.focus })),
    exportUrl: (wsId, name, format = "md") =>
      `${at(wsId, name)}/export?format=${encodeURIComponent(format)}`,
  };
}
