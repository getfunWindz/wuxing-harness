/** 桌面承载能力探测（Electron preload 注入的 `wuxingDesktop` 桥）。
 *
 * 浏览器承载下桥不存在 → 调用方按特性检测降级（架构方案 §7.5）。
 */

export interface DesktopBridge {
  platform: string;
  electronVersion: string;
  /** A6（W1-6）：系统默认程序打开本地文件（""=成功，否则错误文案；缺失=旧桥不支持） */
  openPath?: (target: string) => Promise<string>;
}

export function readDesktopBridge(scope: unknown): DesktopBridge | null {
  if (typeof scope !== "object" || scope === null) {
    return null;
  }
  const candidate = (scope as { wuxingDesktop?: unknown }).wuxingDesktop;
  if (typeof candidate !== "object" || candidate === null) {
    return null;
  }
  const { platform, electronVersion, openPath } = candidate as Record<string, unknown>;
  if (typeof platform !== "string" || typeof electronVersion !== "string") {
    return null;
  }
  const bridge: DesktopBridge = { platform, electronVersion };
  if (typeof openPath === "function") {
    bridge.openPath = (target: string): Promise<string> =>
      (openPath as (t: string) => Promise<string>).call(candidate, target);
  }
  return bridge;
}

export function isDesktopCarrier(scope: unknown): boolean {
  return readDesktopBridge(scope) !== null;
}
