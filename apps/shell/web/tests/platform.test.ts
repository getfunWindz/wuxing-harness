import { test } from "node:test";
import assert from "node:assert/strict";

import {
  isDesktopCarrier,
  readDesktopBridge,
} from "../src/platform/capabilities.ts";

test("无桥时返回 null（浏览器承载）", () => {
  assert.equal(readDesktopBridge({}), null);
  assert.equal(readDesktopBridge(globalThis), null);
  assert.equal(isDesktopCarrier({}), false);
});

test("合法桥被识别", () => {
  const bridge = { platform: "win32", electronVersion: "38.0.0" };
  assert.deepEqual(readDesktopBridge({ wuxingDesktop: bridge }), bridge);
  assert.equal(isDesktopCarrier({ wuxingDesktop: bridge }), true);
});

test("残缺桥视为不存在", () => {
  assert.equal(readDesktopBridge({ wuxingDesktop: { platform: 1 } }), null);
  assert.equal(readDesktopBridge(null), null);
  assert.equal(readDesktopBridge("desktop"), null);
});

test("openPath（A6）：函数透传；缺失/非函数 = 旧桥（不伪造）", async () => {
  const calls: string[] = [];
  const openPath = async (target: string): Promise<string> => {
    calls.push(target);
    return "";
  };
  const bridge = readDesktopBridge({ wuxingDesktop: {
    platform: "win32", electronVersion: "38.0.0", openPath,
  } });
  assert.ok(bridge?.openPath !== undefined);
  assert.equal(await bridge.openPath("C:/ws/a.md"), "");
  assert.deepEqual(calls, ["C:/ws/a.md"]);

  const legacy = readDesktopBridge({ wuxingDesktop: {
    platform: "win32", electronVersion: "38.0.0",
  } });
  assert.equal(legacy?.openPath, undefined);
  const bad = readDesktopBridge({ wuxingDesktop: {
    platform: "win32", electronVersion: "38.0.0", openPath: 1,
  } });
  assert.equal(bad?.openPath, undefined);   // 非函数不得伪造可调用面
});
