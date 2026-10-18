/** TDD · O2-2 §11.5-③：storage-state 纯模块（解析/校验/注入计划——零 Electron）。 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  cookieParams,
  parseStorageState,
} = require("../dist/browser-storage-state.js") as typeof import("../src/browser-storage-state.ts");

const GOOD = JSON.stringify({
  cookies: [
    { name: "sid", value: "abc", domain: "127.0.0.1", path: "/",
      expires: 4102444800, httpOnly: true, secure: false, sameSite: "Lax" },
  ],
  origins: [
    { origin: "http://127.0.0.1:8897",
      localStorage: [{ name: "token", value: "t1" }] },
  ],
});

test("parseStorageState：合法解析 + 计数", () => {
  const r = parseStorageState(GOOD);
  assert.equal(r.ok, true);
  if (r.ok) {
    assert.equal(r.counts.cookies, 1);
    assert.equal(r.counts.origins, 1);
    assert.equal(r.cookies[0].name, "sid");
    assert.equal(r.origins[0].localStorage[0].value, "t1");
  }
});

test("parseStorageState：坏 JSON / 缺数组 / 空表 / 条目非法 → 拒", () => {
  for (const bad of [
    "{bad",
    JSON.stringify({ cookies: [], origins: [] }),
    JSON.stringify({ cookies: "x", origins: [] }),
    JSON.stringify({ cookies: [{ name: "a" }], origins: [] }),        // 缺 value/domain
    JSON.stringify({ cookies: [], origins: [{ origin: "not-a-url", localStorage: [] }] }),
    JSON.stringify({ cookies: [], origins: [{ origin: "http://x", localStorage: [{ name: 1 }] }] }),
  ]) {
    assert.equal(parseStorageState(bad).ok, false, bad.slice(0, 60));
  }
});

test("cookieParams：Electron cookies.set 参数映射（url/scheme/expires/sameSite）", () => {
  const p = cookieParams({
    name: "sid", value: "abc", domain: ".example.com", path: "/app",
    expires: 4102444800, httpOnly: true, secure: true, sameSite: "None",
  });
  assert.equal(p.name, "sid");
  assert.equal(p.url, "https://example.com/app");
  assert.equal(p.expirationDate, 4102444800);
  assert.equal(p.sameSite, "None");
  assert.equal(p.httpOnly, true);
});
