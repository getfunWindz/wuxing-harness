/** 装配预设服务（E2-UI）：预设清单/解析态 + 会话绑定。
    —— 读（清单/绑定）直连 REST；写（绑定）走命令总线（失败全局可见）。
    —— 依赖后端 `GET …/presets`、`GET/PUT …/session-preset`。 */
import type {
  AssemblyPresetListDto,
  SessionPresetDto,
} from "../../protocol/generated.ts";
import type { CommandBus } from "../commands.ts";
import type { WritableRestClient } from "../connection/rest.ts";

export interface PresetsService {
  /** 预设清单（含解析态 chain/hash/error）。 */
  list(wsId: string): Promise<AssemblyPresetListDto>;
  /** 会话绑定读取（name 空 = 跟随默认）。 */
  session(wsId: string, session: string): Promise<SessionPresetDto>;
  /** 会话绑定写入（name 空 = 清除绑定）。 */
  setSession(wsId: string, session: string, name: string): Promise<SessionPresetDto>;
}

export function createPresetsService(deps: {
  rest: WritableRestClient;
  commands: CommandBus;
}): PresetsService {
  const url = (wsId: string, session: string): string =>
    `/api/v1/workspaces/${wsId}/session-preset?session=${encodeURIComponent(session)}`;
  return {
    // 读取：后台只读刷新（直连——同 modes.get 口径）
    list: (wsId) =>
      deps.rest.get<AssemblyPresetListDto>(`/api/v1/workspaces/${wsId}/presets`),
    session: (wsId, session) =>
      deps.rest.get<SessionPresetDto>(url(wsId, session)),
    // 写入：用户动作（走总线；失败全局可见）
    setSession: (wsId, session, name) =>
      deps.commands.run("presets.bind", () =>
        deps.rest.put<SessionPresetDto>(url(wsId, session), { session, name })),
  };
}
