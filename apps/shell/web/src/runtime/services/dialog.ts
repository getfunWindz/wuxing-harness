/** 系统对话框桥（R1-1/R2-1 规范化）：文件/目录选择一律经系统对话框。
    —— 浏览器承载经服务端桥（本地特权端点）；Electron 承载同端点语义一致。
    —— 只读调用；失败经命令总线可见。 */
import type { DialogPickDto } from "../../protocol/generated.ts";
import type { CommandBus } from "../commands.ts";
import type { WritableRestClient } from "../connection/rest.ts";

export interface DialogService {
  /** 选择文件（多选）——返回绝对路径列表（空列表 = 用户取消）。 */
  pickFiles(): Promise<DialogPickDto>;
  /** 选择文件夹（新建工作区用）——返回绝对路径（空 = 取消）。 */
  pickDirectory(): Promise<DialogPickDto>;
}

export function createDialogService(deps: {
  rest: WritableRestClient;
  commands: CommandBus;
}): DialogService {
  return {
    pickFiles: () =>
      deps.commands.run("dialog.pick", () =>
        deps.rest.post<DialogPickDto>("/api/v1/dialog/pick", { kind: "files" })),
    pickDirectory: () =>
      deps.commands.run("dialog.pick.dir", () =>
        deps.rest.post<DialogPickDto>("/api/v1/dialog/pick", { kind: "directory" })),
  };
}
