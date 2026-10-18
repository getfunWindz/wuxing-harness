/** 扩展命令服务（E2-UI）：清单读取（后台只读，直连 REST）+ 执行（用户动作，走命令总线）。
    —— 依赖后端 `GET/POST /api/v1/workspaces/{ws}/extensions/commands[/{name}]`。 */
import type {
  ExtCommandListDto,
  ExtCommandRunDto,
} from "../../protocol/generated.ts";
import type { CommandBus } from "../commands.ts";
import type { WritableRestClient } from "../connection/rest.ts";

export interface ExtensionsService {
  /** 工作区扩展命令清单（含参数声明——参数表单渲染用）。 */
  list(wsId: string): Promise<ExtCommandListDto>;
  /** 执行扩展命令（args 为逐字段表单收集的对象；服务端按声明校验/转换）。 */
  run(wsId: string, name: string, args: Record<string, unknown>): Promise<ExtCommandRunDto>;
}

export function createExtensionsService(deps: {
  rest: WritableRestClient;
  commands: CommandBus;
}): ExtensionsService {
  const base = (wsId: string): string =>
    `/api/v1/workspaces/${wsId}/extensions/commands`;
  return {
    // 读取：后台只读刷新（直连——同 modes.get 口径）
    list: (wsId) => deps.rest.get<ExtCommandListDto>(base(wsId)),
    // 执行：用户动作（走总线；失败全局可见）
    run: (wsId, name, args) =>
      deps.commands.run("extensions.run", () =>
        deps.rest.post<ExtCommandRunDto>(
          `${base(wsId)}/${encodeURIComponent(name)}`, { args })),
  };
}
