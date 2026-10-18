/** 循迹设计服务（双模式批 3）：设计态读取 / 「交给执行」交接 / 地图只读。
 *
 * 纪律：读取与地图为后台只读（直连 REST）；交接为用户动作（走命令总线）。 */
import type { DesignStateDto, MapViewDto, TicketListDto } from "../../protocol/generated.ts";
import type { CommandBus } from "../commands.ts";
import type { WritableRestClient } from "../connection/rest.ts";

export interface DesignService {
  get(wsId: string, session: string): Promise<DesignStateDto>;
  handoff(wsId: string, session: string): Promise<DesignStateDto>;
  map(wsId: string): Promise<MapViewDto>;
  /** 地图原始文件地址（「打开文件」—— artifact 端点） */
  mapFileUrl(wsId: string): string;
  /** 规格原始文件地址（「查看规格」—— artifact 端点；逐段编码保留分隔符） */
  specFileUrl(wsId: string, path: string): string;
  /** 实施票据列表（二期批 4）：工作区级执行清单（后台只读） */
  tickets(wsId: string): Promise<TicketListDto>;
  /** 发布票据（二期批 4）：用户 quiz 动作（走命令总线——失败全局可见） */
  publishTickets(wsId: string, ids?: readonly string[]): Promise<TicketListDto>;
}

export function createDesignService(deps: {
  rest: WritableRestClient;
  commands: CommandBus;
}): DesignService {
  const stateUrl = (wsId: string, session: string): string =>
    `/api/v1/workspaces/${wsId}/design-state?session=${encodeURIComponent(session)}`;
  return {
    get: (wsId, session) => deps.rest.get<DesignStateDto>(stateUrl(wsId, session)),
    handoff: (wsId, session) =>
      deps.commands.run("design.handoff", () =>
        deps.rest.put<DesignStateDto>(stateUrl(wsId, session), { phase: "ready" })),
    map: (wsId) => deps.rest.get<MapViewDto>(`/api/v1/workspaces/${wsId}/map`),
    mapFileUrl: (wsId) =>
      `/api/v1/workspaces/${wsId}/artifacts/${encodeURIComponent("WUXING.md")}`,
    specFileUrl: (wsId, path) =>
      `/api/v1/workspaces/${wsId}/artifacts/` +
      path.split("/").map((seg) => encodeURIComponent(seg)).join("/"),
    tickets: (wsId) =>
      deps.rest.get<TicketListDto>(`/api/v1/workspaces/${wsId}/tickets`),
    publishTickets: (wsId, ids) =>
      deps.commands.run("design.publishTickets", () =>
        deps.rest.post<TicketListDto>(
          `/api/v1/workspaces/${wsId}/tickets/publish`,
          ids && ids.length > 0 ? { ids: [...ids] } : {})),
  };
}
