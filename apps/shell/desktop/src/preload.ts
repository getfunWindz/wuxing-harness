/** 原生能力桥（P0 最小：承载标识；P4 扩展；A6：openPath 本地打开）。 */
import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("wuxingDesktop", {
  platform: process.platform,
  electronVersion: process.versions.electron ?? "",
  openPath: (target: string): Promise<string> =>
    ipcRenderer.invoke("wuxing:open-path", String(target ?? "")),
});
