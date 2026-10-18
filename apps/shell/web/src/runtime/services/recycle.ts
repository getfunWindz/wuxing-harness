/** 回收站服务（P2-M1）：列表 / 恢复 / 彻底删除（写操作——经命令总线可见失败）。 */
import type { RecycleListDto } from "../../protocol/generated.ts";
import type { CommandBus } from "../commands.ts";
import type { WritableRestClient } from "../connection/rest.ts";

export interface RecycleService {
  list(): Promise<RecycleListDto>;
  restore(id: string): Promise<void>;
  purge(id: string): Promise<void>;
}

export function createRecycleService(deps: {
  rest: WritableRestClient;
  commands: CommandBus;
}): RecycleService {
  const at = (id: string): string => `/api/v1/recycle/${encodeURIComponent(id)}`;
  return {
    list: () =>
      deps.commands.run("recycle.list", () =>
        deps.rest.get<RecycleListDto>("/api/v1/recycle")),
    restore: async (id) => {
      await deps.commands.run("recycle.restore", () =>
        deps.rest.post(at(id) + "/restore"));
    },
    purge: async (id) => {
      await deps.commands.run("recycle.purge", () =>
        deps.rest.del(at(id) + "?purge=true"));
    },
  };
}
